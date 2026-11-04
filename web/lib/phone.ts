import "server-only";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { RoomServiceClient } from "livekit-server-sdk";
import { db, speechSettings, UserError } from "./consultation";
const execute = promisify(execFile);

export async function phoneRequest(path: string, body?: object) {
  if (!process.env.PHONE_CONSOLE_PASSWORD)
    throw new UserError("私有线路服务未配置", 503);
  const r = await fetch("http://127.0.0.1:5055/api/" + path, {
    method: body ? "POST" : "GET",
    headers: {
      Authorization:
        "Basic " +
        Buffer.from("operator:" + process.env.PHONE_CONSOLE_PASSWORD).toString(
          "base64",
        ),
      ...(body
        ? {
            "Content-Type": "application/json",
            Origin: "http://127.0.0.1:5055",
            "X-Phone-Console": "1",
          }
        : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
    signal: AbortSignal.timeout(12000),
  });
  const result = await r.json();
  if (!r.ok)
    throw new UserError(result.error || "私有电话服务不可用", r.status);
  return result;
}

export async function phoneReadiness() {
  const saved =
    (await db.query("SELECT value FROM consult_settings WHERE id='line'"))
      .rows[0]?.value || {};
  let line = {
    gateway_online: false,
    busy: false,
    numbers: [] as string[],
    actual_sim: 2,
    caller: "19221659824",
    max_seconds: 180,
  };
  let available = false,
    agent = false,
    rtc = false;
  await Promise.allSettled([
    phoneRequest("status").then((v) => {
      line = v;
      available = true;
    }),
    execute("systemctl", ["is-active", "persona-voice-agent"], {
      timeout: 3000,
    }).then((r) => {
      agent = r.stdout.trim() === "active";
    }),
    (async () => {
      if (
        !process.env.LIVEKIT_URL ||
        !process.env.LIVEKIT_API_KEY ||
        !process.env.LIVEKIT_API_SECRET
      )
        return;
      const rooms = new RoomServiceClient(
        process.env.LIVEKIT_URL.replace(/^ws/, "http"),
        process.env.LIVEKIT_API_KEY,
        process.env.LIVEKIT_API_SECRET,
      );
      await Promise.race([
        rooms.listRooms(),
        new Promise((_, reject) =>
          setTimeout(() => reject(Error("rtc_timeout")), 3000),
        ),
      ]);
      rtc = true;
    })(),
  ]);
  const speech = await speechSettings();
  const checks = [
    {
      id: "console",
      label: "私有拨号服务",
      ok: available,
      detail: available ? "仅服务器本机可访问" : "无法读取私有控制台",
    },
    {
      id: "gateway",
      label: "手机 SIP 线路",
      ok: line.gateway_online,
      detail: line.gateway_online
        ? "Asterisk 探测可达"
        : "手机未注册或探测超时，请检查联网、Shizuku 和网关",
    },
    {
      id: "idle",
      label: "线路空闲",
      ok: !line.busy,
      detail: line.busy ? "已有电话或待确认拨号" : "无活动电话",
    },
    {
      id: "agent",
      label: "语音 Agent 与 LiveKit",
      ok: agent && rtc,
      detail:
        agent && rtc
          ? "进程运行、房间服务可访问"
          : "检查 Agent 或 LiveKit 服务",
    },
    {
      id: "asr",
      label: "千问 ASR",
      ok: !!(speech.configured && speech.asr_test?.ok),
      detail: "依据当前 Key 的最近录音测试；不保证供应商此刻可用",
    },
    {
      id: "tts",
      label: "千问 TTS",
      ok: !!(speech.configured && speech.tts_test?.ok),
      detail: "依据当前 Key 的最近合成测试",
    },
    {
      id: "llm",
      label: "DeepSeek",
      ok: !!process.env.DEEPSEEK_API_KEY,
      detail: "服务端凭据已配置；余额与实时可用性以调用结果为准",
    },
  ];
  return {
    caller: line.caller,
    recipient: saved.recipient || "13660199577",
    sim: line.actual_sim,
    online: line.gateway_online,
    busy: line.busy,
    status_available: available,
    numbers: line.numbers,
    max_seconds: line.max_seconds,
    checks,
    dial_enabled: checks.every((c) => c.ok),
    reason:
      checks
        .filter((c) => !c.ok)
        .map((c) => c.label + "未就绪")
        .join("；") || "基础检查通过；点击拨打会呼叫真实手机",
    checked_at: new Date().toISOString(),
  };
}
