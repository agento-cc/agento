-- Per-mailbox Microsoft Graph delta cursor. Decouples publisher poll progress from isRead:
-- the publisher resumes the messages/delta query from delta_link (the full @odata.deltaLink URL Graph
-- returned) instead of re-scanning unread. Keyed by the NORMALIZED mailbox UPN (lower-cased) -- the same
-- key as the publisher's seen_mailboxes dedupe -- so a mailbox shared by multiple agent_views has exactly
-- one cursor row. The toolbox re-validates this URL as belonging to the resolved mailbox before using it.
CREATE TABLE IF NOT EXISTS outlook_poll_cursor (
    mailbox     VARCHAR(255) NOT NULL PRIMARY KEY,
    delta_link  TEXT         NOT NULL,
    updated_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
