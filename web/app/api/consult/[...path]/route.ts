import { NextRequest, NextResponse } from "next/server";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import {
  db,
  initDB,
  UserError,
  authenticate,
  checkOrigin,
  login,
  hash,
  event,
  session,
  turn,
  generateReport,
  exportMarkdown,
  template,
  speechSettings,
  seal,
  limit,
} from "@/lib/consultation";
import { toWav } from "@/lib/qwen-asr";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
let initialized: Promise<void> | undefined;
async function setup() {
  try {
    await (initialized ??= initDB());
  } catch (e) {
    initialized = undefined;
    throw e;
  }
}
const json = (data: unknown, status = 200) =>
  NextResponse.json(data, { status, headers: { "Cache-Control": "no-store" } });
function failure(e: unknown) {
  return json(
    {
      error:
        e instanceof UserError
          ? e.message
          : "服务暂不可用，请稍后重试；已保存的内容不会因此清除",
    },
    e instanceof UserError ? e.status : 503,
  );
}

export async function GET(req: NextRequest) {
  try {
    await setup();
    await authenticate(req);
    const path = req.nextUrl.pathname.split("/api/consult/")[1];
    if (path === "me")
      return json({ authenticated: true, role: "operator", template });
    if (path === "sessions")
      return json(
        (
          await db.query(
            "SELECT id,title,status,created_at,ended_at,report_status FROM consult_sessions ORDER BY created_at DESC LIMIT 100",
          )
        ).rows,
      );
    if (path === "speech") return json(await speechSettings());
    if (path === "line") {
      let online = false,
        busy = false,
        available = false;
      try {
        if (process.env.PHONE_CONSOLE_PASSWORD) {
          const r = await fetch("http://127.0.0.1:5055/api/status", {
            headers: {
              Authorization:
                "Basic " +
                Buffer.from(
                  "operator:" + process.env.PHONE_CONSOLE_PASSWORD,
                ).toString("base64"),
            },
            signal: AbortSignal.timeout(3000),
            cache: "no-store",
          });
          if (r.ok) {
            const v = await r.json();
            online = !!v.gateway_online;
            busy = !!v.busy;
            available = true;
          }
        }
      } catch {}
      const saved = (
        await db.query("SELECT value FROM consult_settings WHERE id='line'")
      ).rows[0]?.value || {
        caller: "19221659824",
        recipient: "15820242347",
        sim: 2,
      };
      return json({
        ...saved,
        online,
        busy,
        status_available: available,
        dial_enabled: false,
        reason: "本阶段仅开放文字咨询；电话接入待语音配置及线路验收完成。",
      });
    }
    const id = req.nextUrl.searchParams.get("id") || "";
    if (path === "session") return json(await session(id));
    if (path === "events") {
      await session(id);
      return json(
        (
          await db.query(
            "SELECT seq,kind,payload,created_at FROM consult_events WHERE session_id=$1 ORDER BY seq",
            [id],
          )
        ).rows,
      );
    }
    if (path === "export") {
      const kind = req.nextUrl.searchParams.get("kind") || "";
      const text = await exportMarkdown(id, kind);
      await event(id, "export.download", { kind });
      return new NextResponse(text, {
        headers: {
          "Content-Type": "text/markdown; charset=utf-8",
          "Content-Disposition": `attachment; filename="${kind}-${id}.md"`,
          "Cache-Control": "no-store",
          "X-Content-Type-Options": "nosniff",
        },
      });
    }
    return json({ error: "Not found" }, 404);
  } catch (e) {
    return failure(e);
  }
}

async function synthesize(key: string, workspace: string): Promise<Buffer> {
  const root =
    process.env.PERSONA_PROJECT_ROOT || "/home/ubuntu/Project/persona-voice";
  return new Promise((resolve, reject) => {
    const child = spawn(
      root + "/.venv-agent/bin/python",
      [root + "/scripts/test-workspace-tts.py"],
      { stdio: ["pipe", "pipe", "pipe"] },
    );
    const chunks: Buffer[] = [];
    let bytes = 0;
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new UserError("TTS 测试超时", 502));
    }, 45000);
    child.stdout.on("data", (chunk: Buffer) => {
      bytes += chunk.length;
      if (bytes > 4 * 1024 * 1024) {
        child.kill("SIGKILL");
      } else chunks.push(chunk);
    });
    child.stderr.resume();
    child.stdin.on("error", () => {});
    child.on("error", () => {
      clearTimeout(timer);
      reject(new UserError("TTS 测试组件未就绪", 503));
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (code === 0) resolve(Buffer.concat(chunks));
      else
        reject(
          new UserError(
            "TTS 调用失败，请核对 Key、北京业务空间、模型权限和额度",
            502,
          ),
        );
    });
    child.stdin.end(JSON.stringify({ key, workspace }));
  });
}
export async function POST(req: NextRequest) {
  let testedKind: string | null = null,
    testRevision: string | null = null;
  try {
    await setup();
    checkOrigin(req);
    const path = req.nextUrl.pathname.split("/api/consult/")[1];
    if (path === "login") {
      if (Number(req.headers.get("content-length")) > 4096)
        throw new UserError("请求过大");
      const body = await req.json();
      const token = await login(
        typeof body.password === "string" ? body.password : "",
        req,
      );
      const r = json({ ok: true });
      r.cookies.set("consultation_session", token, {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "strict",
        maxAge: 43200,
        path: "/",
      });
      return r;
    }
    await authenticate(req);
    if (path === "logout") {
      await db.query("DELETE FROM consult_auth WHERE token_hash=$1", [
        hash(req.cookies.get("consultation_session")?.value || ""),
      ]);
      const r = json({ ok: true });
      r.cookies.delete("consultation_session");
      return r;
    }
    if (path === "test-asr" || path === "test-tts") {
      await limit("speech-tests", 12, 600);
      const config = await speechSettings(true);
      if (!config.configured || !config.key)
        throw new UserError("请先保存千问 Key");
      testedKind = path === "test-asr" ? "asr_test" : "tts_test";
      testRevision = config.revision;
      await event(null, "speech.test_started", {
        kind: testedKind,
        revision: testRevision,
      });
      let response: NextResponse;
      if (path === "test-tts") {
        const wav = await synthesize(config.key, config.workspace);
        if (wav.length < 1000 || wav.toString("ascii", 0, 4) !== "RIFF")
          throw new UserError("TTS 未返回有效音频", 502);
        response = new NextResponse(new Uint8Array(wav), {
          headers: { "Content-Type": "audio/wav", "Cache-Control": "no-store" },
        });
      } else {
        if (Number(req.headers.get("content-length")) > 6 * 1024 * 1024)
          throw new UserError("音频不能超过 5MB");
        const form = await req.formData();
        const file = form.get("audio");
        if (
          !(file instanceof File) ||
          !file.size ||
          file.size > 5 * 1024 * 1024
        )
          throw new UserError("请选择不超过 5MB 的短语音文件");
        const wav = await toWav(Buffer.from(await file.arrayBuffer()));
        const upstream = await fetch(
          (config.workspace ? `https://${config.workspace}.cn-beijing.maas.aliyuncs.com/api/v1` : 'https://dashscope.aliyuncs.com/api/v1') + '/services/aigc/multimodal-generation/generation',
          {
            method: "POST",
            headers: {
              Authorization: "Bearer " + config.key,
              "Content-Type": "application/json",
              "X-DashScope-SSE": "disable",
            },
            body: JSON.stringify({
              model: "qwen-audio-3.1-asr-flash",
              input: {
                messages: [
                  {
                    role: "user",
                    content: [
                      {
                        type: "input_audio",
                        input_audio: {
                          data:
                            "data:audio/wav;base64," + wav.toString("base64"),
                        },
                      },
                    ],
                  },
                ],
              },
              parameters: { format: "wav", sample_rate: "16000" },
            }),
            signal: AbortSignal.timeout(45000),
          },
        );
        if (!upstream.ok)
          throw new UserError(
            `千问录音 ASR 测试失败（${upstream.status}），请检查 Key、业务空间和音频`,
            502,
          );
        const body = await upstream.json();
        const text =
          body.text ?? body.output?.text ?? body.output?.sentence?.text ?? body.output?.output?.text;
        if (typeof text !== "string" || !text.trim())
          throw new UserError("未识别到有效文字，请检查音频人声", 422);
        response = json({
          text,
          notice: "本次验证录音 ASR，不代表实时 ASR 或电话音频已验收。",
        });
      }
      await db.query(
        `UPDATE consult_settings SET value=jsonb_set(value,ARRAY[$1]::text[],$2::jsonb),updated_at=now() WHERE id='speech' AND value->>'revision'=$3`,
        [
          testedKind,
          JSON.stringify({ ok: true, at: new Date().toISOString() }),
          testRevision,
        ],
      );
      await event(null, "speech.test_succeeded", {
        kind: testedKind,
        revision: testRevision,
      });
      return response;
    }
    if (Number(req.headers.get("content-length")) > 12000)
      throw new UserError("请求过大");
    const b = await req.json();
    if (path === "speech") {
      if (
        typeof b.key !== "string" ||
        b.key.length < 20 ||
        b.key.length > 512 ||
        /\s/.test(b.key)
      )
        throw new UserError("请输入有效 Key");
      if (
        typeof b.workspace !== "string" ||
        (b.workspace !== '' && !/^llm-[a-zA-Z0-9-]{5,80}$/.test(b.workspace))
      )
        throw new UserError("请输入北京业务空间 ID（llm- 开头），或留空使用官方默认入口");
      const value = {
        encrypted: seal(b.key),
        workspace: b.workspace,
        revision: randomUUID(),
        asr_test: null,
        tts_test: null,
      };
      await db.query(
        "INSERT INTO consult_settings VALUES('speech',$1,now()) ON CONFLICT(id) DO UPDATE SET value=$1,updated_at=now()",
        [JSON.stringify(value)],
      );
      await event(null, "speech.saved", { revision: value.revision });
      return json({ ok: true });
    }
    if (path === "line") {
      if (
        !/^1[0-9]{10}$/.test(b.caller) ||
        !/^1[0-9]{10}$/.test(b.recipient) ||
        ![1, 2].includes(b.sim)
      )
        throw new UserError("请输入有效号码及 SIM 1 或 2");
      const value = { caller: b.caller, recipient: b.recipient, sim: b.sim };
      await db.query(
        "INSERT INTO consult_settings VALUES('line',$1,now()) ON CONFLICT(id) DO UPDATE SET value=$1,updated_at=now()",
        [JSON.stringify(value)],
      );
      await event(null, "line.preferences_saved", { sim: b.sim });
      return json({
        ok: true,
        notice: "已保存线路偏好，尚未修改手机或 Asterisk 实际配置。",
      });
    }
    if (path === "create") {
      await limit("create", 20, 3600);
      if (b.consent !== true)
        throw new UserError("请先确认文字保存与非诊断声明");
      const id = randomUUID();
      const title =
        typeof b.title === "string"
          ? b.title.trim().slice(0, 80)
          : "睡眠习惯咨询";
      await db.query(
        "INSERT INTO consult_sessions(id,title,template) VALUES($1,$2,$3)",
        [id, title || "睡眠习惯咨询", JSON.stringify(template)],
      );
      await event(id, "session.created", {
        template: "sleep-v1",
        mode: "text",
        consent: true,
      });
      return json({ id }, 201);
    }
    const id = typeof b.id === "string" ? b.id : "";
    await session(id);
    if (path === "turn")
      return json(
        await turn(
          id,
          typeof b.text === "string" ? b.text : null,
          String(b.requestId || ""),
          b.finish === true,
        ),
      );
    if (path === "report") return json(await generateReport(id));
    if (path === "delete") {
      const c = await session(id);
      if (c.lease_until && new Date(c.lease_until).getTime() > Date.now())
        throw new UserError("当前仍在处理，请稍后删除", 409);
      await db.query("DELETE FROM consult_sessions WHERE id=$1", [id]);
      await event(null, "session.deleted", { id });
      return json({ ok: true });
    }
    return json({ error: "Not found" }, 404);
  } catch (e) {
    if (testedKind && testRevision) {
      await db
        .query(
          `UPDATE consult_settings SET value=jsonb_set(value,ARRAY[$1]::text[],$2::jsonb) WHERE id='speech' AND value->>'revision'=$3`,
          [
            testedKind,
            JSON.stringify({ ok: false, at: new Date().toISOString() }),
            testRevision,
          ],
        )
        .catch(() => {});
      await event(null, "speech.test_failed", {
        kind: testedKind,
        error: e instanceof UserError ? e.message : "test_error",
      }).catch(() => {});
    }
    return failure(e);
  }
}
