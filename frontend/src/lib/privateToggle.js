// Show the "hide description from household" toggle only when it can matter:
// a multi-member household AND a shared envelope. (Plan C2 §8.3)
//
// Shared == no owner. We gate on `owner_id` (not `is_personal`) because the
// GET /envelopes/ response this consumes always serializes is_personal=false
// (it is not an ORM attribute — only owner_id is), whereas owner_id is real:
// null for shared, a user id for personal.
export function shouldShowPrivateToggle(memberCount, envelope) {
  return memberCount > 1 && !!envelope && envelope.owner_id == null;
}
