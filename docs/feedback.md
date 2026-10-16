# Feedback process (Milestone 7 public beta)

## Intake

- Web form `/feedback` (optional report link, optional contact).
  Empty messages are refused (400); oversized POSTs are refused (413);
  submitters are rate-limited like all POSTs.
- CLI triage: `lawradar feedback list [--status]` shows the queue;
  `lawradar feedback resolve <id>` closes entries.

## Triage (maintainer, within one working week)

1. Read the message; open the linked report (if any).
2. Compare the disputed claim against the **official source URL** on
   the report — never against memory or another secondary source.
3. Decide:
   - Report is wrong → `review <id> --reject/--changes --notes` with
     the correction; fix the pipeline cause if systemic.
   - Report is right → reply via contact (if given); resolve feedback.
   - Unclear → keep open, note what evidence is missing.
4. Feedback linked to a report auto-opens a `user-reported error`
   review task, so nothing reported is silently dropped.

## What feedback is not

Not legal advice intake, not document filing, not a chat channel.
Personal or client confidences submitted by mistake are deleted on
request (contact the operator; nothing is shared with third parties —
see `/privacy`).
