import { NextRequest, NextResponse } from "next/server";
import { createHash, timingSafeEqual } from "node:crypto";
import { db, initDB, generateReport } from "@/lib/consultation";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
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
    await initDB();
    const b = await req.json();
    if (
      !/^[0-9a-f-]{36}$/.test(b.call_id) ||
      !/^[0-9a-f-]{36}$/.test(b.event_id) ||
      ![
        "queued",
        "dialing",
        "connected",
        "uncertain",
        "ended",
        "failed",
      ].includes(b.state) ||
      !Number.isFinite(b.at)
    )
      throw Error("invalid");
    const c = (
      await db.query(
        "SELECT * FROM consult_sessions WHERE id=$1 AND mode='phone'",
        [b.call_id],
      )
    ).rows[0];
    if (!c) return NextResponse.json({ error: "Not found" }, { status: 404 });
    const client = await db.connect();
    try {
      await client.query("BEGIN");
      const added = await client.query(
        "INSERT INTO consult_events(session_id,kind,payload,event_id) VALUES($1,'phone.state',$2,$3) ON CONFLICT(event_id) WHERE event_id IS NOT NULL DO NOTHING RETURNING seq",
        [
          b.call_id,
          JSON.stringify({
            state: b.state,
            reason: String(b.reason).slice(0, 100),
            at: b.at,
          }),
          b.event_id,
        ],
      );
      if (added.rowCount)
        await client.query(
          "UPDATE consult_sessions SET phone_state=$2,phone_updated_at=to_timestamp($3) WHERE id=$1 AND (phone_updated_at IS NULL OR phone_updated_at<=to_timestamp($3))",
          [b.call_id, b.state, b.at],
        );
      await client.query("COMMIT");
    } catch (e) {
      await client.query("ROLLBACK");
      throw e;
    } finally {
      client.release();
    }
    if (["ended", "failed"].includes(b.state) && c.status === "active") {
      // Let the Agent flush final playback transcripts before fallback archival.
      if (c.room_name && Date.now() / 1000 - b.at < 30)
        return NextResponse.json({ retry: true }, { status: 503 });
      await db.query(
        "UPDATE consult_sessions SET status='closed',voice_state='ended',ended_at=COALESCE(ended_at,now()),reason=COALESCE(reason,$2) WHERE id=$1 AND status='active'",
        [b.call_id, c.room_name ? "phone_disconnected" : "phone_not_connected"],
      );
      await generateReport(b.call_id).catch(() => {});
    }
    return NextResponse.json({ ok: true });
  } catch {
    return NextResponse.json(
      { error: "Phone status unavailable" },
      { status: 503 },
    );
  }
}
