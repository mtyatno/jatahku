// Show the "hide description from household" toggle only when it can matter:
// a multi-member household AND a shared (non-personal) envelope. (Plan C2 §8.3)
export function shouldShowPrivateToggle(memberCount, envelope) {
  return memberCount > 1 && !!envelope && envelope.is_personal === false;
}
