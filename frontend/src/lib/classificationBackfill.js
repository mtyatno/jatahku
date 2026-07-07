// Which envelopes still need a needs/wants classification (Plan C2 §8.2).
import { needsClassification } from './envelopeClassification.js';

export function unclassifiedEnvelopes(envelopes) {
  return (envelopes || []).filter(
    e => needsClassification(e.purpose) && (e.classification === null || e.classification === undefined),
  );
}
