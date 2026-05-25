/**
 * Cloudflare Email Routing Worker for newsletter ingestion.
 *
 * Trigger: Cloudflare Email Routing rule for `ai-research@drifting.space`
 * (Zone: drifting.space). Each inbound message invokes `email(...)` and the
 * Worker forwards a small JSON envelope to the Flask webhook on the
 * trading dashboard.
 *
 * Flask handler: web_dashboard/app.py -> webhook_newsletter()
 *   POST https://ai-trading.drifting.space/api/webhooks/newsletter
 *   { from, to, subject, raw_eml }   (Content-Type: application/json)
 *
 * History:
 *   - Pre-2026-05-15: inbound mail routed via Mailgun Routes (form data).
 *   - 2026-05-15: Mailgun quota exhausted -> ingest stopped.
 *   - 2026-05-22: zone MX moved to Cloudflare, this Worker created, and
 *     the Email Routing rule attached.
 *
 * When this file changes, redeploy with `wrangler deploy` from this folder
 * (see README.md). Keeping the source in-tree avoids the previous situation
 * where the Worker only existed in the Cloudflare dashboard.
 */
export default {
  async email(message, env, ctx) {
    // Cloudflare provides the raw email stream. We read it into text.
    const rawEmail = await new Response(message.raw).text();

    // Fire the POST request to your API
    const response = await fetch("https://ai-trading.drifting.space/api/webhooks/newsletter", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: message.headers.get("from"),
        to: message.headers.get("to"),
        subject: message.headers.get("subject"),
        raw_eml: rawEmail
      })
    });

    if (!response.ok) {
      message.setReject("Webhook failed to process the email.");
    }
  }
}
