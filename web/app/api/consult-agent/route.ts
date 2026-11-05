import { NextRequest, NextResponse } from "next/server";
import { createHash, randomUUID, timingSafeEqual } from "node:crypto";
import {
  db,
  initDB,
  template,
  speechSettings,
  generateReport,
} from "@/lib/consultation";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
let initialized: Promise<void> | undefined;
const digest = (s: string) => createHash("sha256").update(s).digest();
export async function POST(req: NextRequest) {
  const secret = process.env.CONSULTATION_AGENT_SECRET || "";
  if (
    secret.length < 32 ||
    !timingSafeEqual(
      digest(req.headers.get("authorization") || ""),
      digest("Bearer " + secret),
    )
  )
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    try {
      await (initialized ??= initDB());
    } catch (e) {
      initialized = undefined;
      throw e;
    }
    const b = await req.json();
    if (
      typeof b.room !== "string" ||
      !/^(consult-[0-9a-f-]{36}|sim-ai-[\w-]{1,120})$/.test(b.room)
    )
      throw Error("room");
    if (b.action === "open") {
      if (b.room.startsWith("sim-ai-")) {
        if (b.consultation_id) {
          if (!/^[0-9a-f-]{36}$/.test(b.consultation_id))
            throw Error("call_id");
          const linked = await db.query(
            "UPDATE consult_sessions SET room_name=$1 WHERE id=$2 AND mode='phone' AND status='active' AND (room_name IS NULL OR room_name=$1) RETURNING id",
            [b.room, b.consultation_id],
          );
          if (!linked.rowCount) throw Error("call_unavailable");
        } else
          await db.query(
            "INSERT INTO consult_sessions(id,title,template,mode,room_name,voice_state) VALUES($1,$2,$3,'phone',$4,'connecting') ON CONFLICT(room_name) WHERE room_name IS NOT NULL DO NOTHING",
            [randomUUID(), "电话自由对话", JSON.stringify(template), b.room],
          );
      }
      const found = await db.query(
        "UPDATE consult_sessions SET voice_state='active' WHERE room_name=$1 AND status='active' AND mode IN ('voice','phone') RETURNING id,title,mode",
        [b.room],
      );
      if (!found.rowCount)
        return NextResponse.json(
          { error: "Session unavailable" },
          { status: 409 },
        );
      const speech = await speechSettings(true);
      if (
        !speech.configured ||
        !speech.key ||
        !speech.asr_test?.ok ||
        !speech.tts_test?.ok
      )
        return NextResponse.json(
          { error: "Speech not ready" },
          { status: 409 },
        );
      return NextResponse.json(
        {
          ...found.rows[0],
          speech: { key: speech.key, workspace: speech.workspace },
        },
        { headers: { "Cache-Control": "no-store" } },
      );
    }
    const found = await db.query(
      "SELECT id,status,voice_state FROM consult_sessions WHERE room_name=$1",
      [b.room],
    );
    if (!found.rowCount)
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    const s = found.rows[0];
    if (b.action === "heartbeat")
      return NextResponse.json({
        ending: s.voice_state === "ending",
        closed: s.status === "closed",
      });
    if (!/^[0-9a-f-]{36}$/.test(b.event_id)) throw Error("event_id");
    const client = await db.connect();
    try {
      await client.query("BEGIN");
      const payload =
        b.payload && typeof b.payload === "object" ? b.payload : {};
      if (JSON.stringify(payload).length > 20000) throw Error("payload");
      const accepted = await client.query(
        "INSERT INTO consult_events(session_id,kind,payload,event_id) VALUES($1,$2,$3,$4) ON CONFLICT(event_id) WHERE event_id IS NOT NULL DO NOTHING RETURNING seq",
        [
          s.id,
          "voice." + String(b.action).slice(0, 60),
          JSON.stringify(payload),
          b.event_id,
        ],
      );
      if (accepted.rowCount) {
        if (b.action === "message") {
          if (
            !["user", "assistant"].includes(payload.role) ||
            typeof payload.text !== "string" ||
            payload.text.length > 8000
          )
            throw Error("message");
          const hash = createHash("sha256")
            .update(b.room + ":" + String(payload.id))
            .digest("hex")
            .slice(0, 32);
          const id = [
            hash.slice(0, 8),
            hash.slice(8, 12),
            hash.slice(12, 16),
            hash.slice(16, 20),
            hash.slice(20),
          ].join("-");
          await client.query(
            "INSERT INTO consult_messages(id,session_id,role,text,interrupted) VALUES($1,$2,$3,$4,$5) ON CONFLICT(id) DO UPDATE SET text=$4,interrupted=$5",
            [id, s.id, payload.role, payload.text, !!payload.interrupted],
          );
        }
        if (b.action === "ending")
          await client.query(
            "UPDATE consult_sessions SET voice_state='ending' WHERE id=$1 AND status='active'",
            [s.id],
          );
        if (b.action === "closed")
          await client.query(
            "UPDATE consult_sessions SET status='closed',voice_state='ended',ended_at=COALESCE(ended_at,now()),reason=COALESCE(reason,$2) WHERE id=$1",
            [
              s.id,
              String(payload.reason || "voice_disconnected").slice(0, 120),
            ],
          );
      }
      await client.query("COMMIT");
    } catch (e) {
      await client.query("ROLLBACK");
      throw e;
    } finally {
      client.release();
    }
    if (b.action === "closed") await generateReport(s.id).catch(() => {});
    return NextResponse.json({ ok: true, id: s.id });
  } catch {
    return NextResponse.json(
      { error: "Voice event unavailable" },
      { status: 503 },
    );
  }
}
