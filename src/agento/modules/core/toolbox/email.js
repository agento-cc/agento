import { z } from 'zod';
import nodemailer from 'nodemailer';

function matchesWhitelist(email, whitelist) {
  email = email.toLowerCase();
  return whitelist.some(pattern => {
    const regex = new RegExp(
      '^' +
        pattern
          .replace(/[.+^${}()|[\]\\]/g, '\\$&')
          .replace(/\*/g, '[^@]*') +
        '$'
    );
    return regex.test(email);
  });
}

export async function healthcheck({ moduleConfigs }) {
  const cfg = moduleConfigs?.core || {};
  const smtpConfig = {
    host: cfg.smtp_host || null,
    port: parseInt(cfg.smtp_port || '587'),
    user: cfg.smtp_user || null,
    pass: cfg.smtp_pass || null,
  };

  if (!smtpConfig.host || !smtpConfig.user) {
    return [{ tool: 'email_send', status: 'skip', error: 'not configured' }];
  }

  const start = Date.now();
  try {
    const transporter = nodemailer.createTransport({
      host: smtpConfig.host,
      port: smtpConfig.port,
      secure: smtpConfig.port === 465,
      auth: { user: smtpConfig.user, pass: smtpConfig.pass },
    });
    await transporter.verify();
    return [{ tool: 'email_send', status: 'ok', ms: Date.now() - start }];
  } catch (err) {
    return [{ tool: 'email_send', status: 'fail', ms: Date.now() - start, error: err.message }];
  }
}

export function register(server, { log, moduleConfigs, isToolEnabled }) {
  if (isToolEnabled && !isToolEnabled('email_send')) return;
  const cfg = moduleConfigs?.core || {};
  const smtpConfig = {
    host: cfg.smtp_host || null,
    port: parseInt(cfg.smtp_port || '587'),
    user: cfg.smtp_user || null,
    pass: cfg.smtp_pass || null,
    from: cfg.smtp_from || null,
  };

  const whitelist = (cfg.email_whitelist || '')
    .split(',')
    .map(p => p.trim().toLowerCase())
    .filter(Boolean);

  server.tool(
    'email_send',
    [
      'Send an email via SMTP. Recipients are validated against a whitelist.',
      'Only whitelisted addresses are allowed. Blocked recipients return an error.',
      'Example:',
      '  to: "user@example.com", subject: "Diagnostic report", body: "Analysis content..."',
    ].join('\n'),
    {
      user: z.string().email().describe('Your (the LLM agent) email address from SOUL.md — identity credential'),
      to: z.string().describe('Recipient email address'),
      subject: z.string().describe('Email subject'),
      body: z.string().describe('Email body (plain text)'),
    },
    async ({ user, to, subject, body }) => {
      if (!matchesWhitelist(to, whitelist)) {
        log('email_send', 'BLOCKED', `user=${user} to="${to}" - not in whitelist`);
        return {
          content: [{ type: 'text', text: `Error: Recipient "${to}" is not in the allowed recipients whitelist.` }],
          isError: true,
        };
      }

      if (!smtpConfig.host) {
        log('email_send', 'ERROR', `user=${user} - SMTP not configured`);
        return {
          content: [{ type: 'text', text: 'Error: SMTP not configured. Set CONFIG__CORE__SMTP_HOST (or bin/agento config:set core/smtp_host).' }],
          isError: true,
        };
      }

      try {
        const transporter = nodemailer.createTransport({
          host: smtpConfig.host,
          port: smtpConfig.port,
          secure: smtpConfig.port === 465,
          auth: { user: smtpConfig.user, pass: smtpConfig.pass },
        });

        const info = await transporter.sendMail({
          from: smtpConfig.from || smtpConfig.user,
          replyTo: user,
          to,
          subject,
          text: body,
        });

        log('email_send', 'OK', `user=${user} to="${to}" subject="${subject}" msgId=${info.messageId}`);
        return {
          content: [{ type: 'text', text: `Email sent to ${to}. Message ID: ${info.messageId}` }],
        };
      } catch (err) {
        log('email_send', 'ERROR', `user=${user} ${err.message}`);
        return {
          content: [{ type: 'text', text: `Email error: ${err.message}` }],
          isError: true,
        };
      }
    }
  );
}
