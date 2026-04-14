import assert from 'node:assert/strict';
import { resolveFlaggedViews } from '../src/app/flagViews.js';

const base = resolveFlaggedViews({ altProducerUi: false, altStaffUi: false });
assert.equal(base.producerHomeView, 'producer');
assert.equal(base.staffValidatorView, 'qrValidator');
assert.equal(base.staffPosView, 'staffPos');
assert.equal(base.isProducerView('producer'), true);
assert.equal(base.isProducerView('producerAlt'), true);
assert.equal(base.isStaffValidatorView('qrValidator'), true);
assert.equal(base.isStaffValidatorView('qrValidatorAlt'), true);

const alt = resolveFlaggedViews({ altProducerUi: true, altStaffUi: true });
assert.equal(alt.producerHomeView, 'producerAlt');
assert.equal(alt.staffValidatorView, 'qrValidatorAlt');
assert.equal(alt.staffPosView, 'staffPosAlt');
assert.equal(alt.isStaffPosView('staffPosAlt'), true);

console.log('flagViews smoke: OK');
