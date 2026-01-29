import { z } from 'zod';

export async function healthcheck({ db }) {
  const start = Date.now();
  try {
    const pool = db.getCronPool();
    await pool.query('SELECT 1');
    return [{ tool: 'schedule_followup', status: 'ok', ms: Date.now() - start }];
  } catch (err) {
    return [{ tool: 'schedule_followup', status: 'fail', ms: Date.now() - start, error: err.message }];
  }
}

export function register(server, { log, db }) {
  server.tool(
    'schedule_followup',
    [
      'Schedule a follow-up task for yourself. The job will be executed at the specified time.',
      'Use this when you need to check something later, wait for a process to complete, or defer work.',
      'The instructions field should describe exactly what to do when the time comes.',
      'The follow-up will have access to the same task context and all MCP tools.',
      'The source parameter identifies the communication channel (e.g. "jira", "email", "teams").',
      'Examples:',
      '  reference_id: "AI-123", source: "jira", scheduled_at: "2026-02-24T16:30:00", instructions: "Sprawdź czy reindeks się zakończył..."',
      '  reference_id: "msg-abc", source: "email", scheduled_at: "2026-02-25T08:00:00", instructions: "Sprawdź odpowiedź..."',
    ].join('\n'),
    {
      user:          z.string().email().describe('Your (the LLM agent) email address from SOUL.md — identity credential'),
      reference_id:  z.string().describe('Task reference ID (e.g. Jira issue key "AI-123", email message ID, etc.)'),
      source:        z.string().optional().default('jira').describe('Communication channel: "jira", "email", "teams"'),
      scheduled_at:  z.string().describe('When to execute, ISO 8601 datetime in local timezone (e.g. "2026-02-24T16:30:00")'),
      instructions:  z.string().min(10).max(2000).describe('Detailed instructions for what to do when the follow-up fires'),
    },
    async ({ user, reference_id, source, scheduled_at, instructions }) => {
      try {
        const scheduledDate = new Date(scheduled_at);
        if (isNaN(scheduledDate.getTime())) {
          log('schedule_followup', 'ERROR', `user=${user} invalid date: ${scheduled_at}`);
          return {
            content: [{ type: 'text', text: `Error: Invalid datetime format "${scheduled_at}". Use ISO 8601 (e.g. "2026-02-24T16:30:00").` }],
            isError: true,
          };
        }

        if (scheduledDate.getTime() <= Date.now()) {
          log('schedule_followup', 'ERROR', `user=${user} scheduled_at is in the past: ${scheduled_at}`);
          return {
            content: [{ type: 'text', text: `Error: scheduled_at must be in the future. Got: ${scheduled_at}` }],
            isError: true,
          };
        }

        // Idempotency key: minute-granular per source+reference
        const isoMinute = scheduledDate.toISOString().slice(0, 16).replace(':', '');
        const idempotencyKey = `followup:${source}:${reference_id}:${isoMinute}`;

        // Format for MySQL TIMESTAMP
        const mysqlDatetime = scheduledDate.toISOString().slice(0, 19).replace('T', ' ');

        const pool = db.getCronPool();
        const conn = await pool.getConnection();
        try {
          const [result] = await conn.execute(
            `INSERT IGNORE INTO job
               (type, source, reference_id, context, idempotency_key, status, attempt, max_attempts, scheduled_after)
             VALUES
               ('followup', ?, ?, ?, ?, 'TODO', 0, 3, ?)`,
            [source, reference_id, instructions, idempotencyKey, mysqlDatetime]
          );

          if (result.affectedRows > 0) {
            log('schedule_followup', 'OK', `user=${user} source=${source} ref=${reference_id} at=${mysqlDatetime} key=${idempotencyKey}`);
            return {
              content: [{ type: 'text', text:
                `Follow-up scheduled for ${reference_id} (${source}) at ${mysqlDatetime}.\n` +
                `Idempotency key: ${idempotencyKey}` }],
            };
          } else {
            log('schedule_followup', 'DUP', `user=${user} source=${source} ref=${reference_id} key=${idempotencyKey}`);
            return {
              content: [{ type: 'text', text:
                `Follow-up already scheduled for ${reference_id} at that time (duplicate prevented).` }],
            };
          }
        } finally {
          conn.release();
        }
      } catch (err) {
        log('schedule_followup', 'ERROR', `user=${user} ${reference_id} ${err.message}`);
        return {
          content: [{ type: 'text', text: `Schedule error: ${err.message}` }],
          isError: true,
        };
      }
    }
  );
}
