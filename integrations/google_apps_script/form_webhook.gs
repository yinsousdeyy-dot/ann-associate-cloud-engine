/**
 * Ann & Associates Law Firm — Real-Time Google Forms -> Cloud Engine Webhook
 * Attach to any Google Form (Surveys, Academy, or Client Ops) via:
 * Extensions -> Apps Script -> Triggers -> Add Trigger -> onFormSubmit -> On form submit
 */

const CLOUD_ENGINE_BASE_URL = "https://YOUR_CLOUD_ENGINE_DOMAIN";
const FIRM_WEBHOOK_SECRET = "YOUR_WEBHOOK_SHARED_SECRET";
const FORM_CATEGORY = "surveys"; // Change to "academy", "surveys", or "ops"

function onFormSubmit(e) {
  const named = e.namedValues || {};
  const pick = (key, fallback = "") => (named[key] && named[key][0] ? String(named[key][0]).trim() : fallback);

  let payload = {};
  if (FORM_CATEGORY === "surveys") {
    payload = {
      respondent_name: pick("Respondent_Name"),
      organization: pick("Organization", "Independent"),
      chamber: pick("Chamber", "Independent"),
      event_name: pick("Event_Name", "Ann & Associates Event"),
      department: pick("Department", "Academy"),
      rating: parseFloat(pick("Rating", "5")) || 5.0,
      requested_topic: pick("Requested_Topic", "General Legal"),
      feedback: pick("Feedback", "")
    };
  } else if (FORM_CATEGORY === "academy") {
    payload = {
      khmer_name: pick("Khmer_Name"),
      latin_name: pick("Latin_Name"),
      email: pick("Email"),
      phone: pick("Phone"),
      course_title: pick("Course_Title", "Double Your Productivity With AI"),
      payment_method: pick("Payment_Method", "ABA KHQR"),
      price_usd: parseFloat(pick("Price_USD", "0")) || 0
    };
  } else {
    payload = {
      client_name: pick("Client_Name"),
      email: pick("Email"),
      phone: pick("Phone"),
      practice_area: pick("Practice_Area", "Corporate & Tax"),
      urgency: pick("Urgency", "Standard")
    };
  }

  UrlFetchApp.fetch(`${CLOUD_ENGINE_BASE_URL}/webhooks/google-form/${FORM_CATEGORY}`, {
    method: "post",
    contentType: "application/json",
    headers: { "X-Firm-Secret": FIRM_WEBHOOK_SECRET },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
}
