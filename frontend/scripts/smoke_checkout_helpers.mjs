import assert from 'node:assert/strict';
import {
  buildCheckoutBlockReason,
  buildOrderPayload,
  resolveCheckoutServicePct,
  validateCheckoutForm,
} from '../src/app/checkout.js';

const emptyErrors = validateCheckoutForm({
  fullName: 'Jane Doe',
  dni: '12345678',
  phone: '2615550000',
  address: 'Calle 123',
  province: 'Mendoza',
  postalCode: '5500',
  birthDate: '1990-01-01',
  acceptTerms: true,
});
assert.equal(Object.keys(emptyErrors).length, 0);

const badErrors = validateCheckoutForm({ acceptTerms: false });
assert.equal(Boolean(badErrors.fullName), true);
assert.equal(Boolean(badErrors.acceptTerms), true);

assert.equal(resolveCheckoutServicePct({ service_charge_pct: 15 }), 0.15);
assert.equal(resolveCheckoutServicePct({ service_charge_pct: 0.2 }), 0.2);
assert.equal(resolveCheckoutServicePct({ service_charge_pct: -1 }), 0.15);

const payload = buildOrderPayload({
  publicTenant: 'tenant-a',
  selectedEvent: { slug: 'evento-1' },
  selectedTicket: { id: 99 },
  quantity: 2,
  method: 'mp',
  selectedSellerCode: 'SELLER-1',
  checkoutForm: {
    fullName: 'Jane Doe',
    dni: '12.345.678',
    phone: '(261) 555-0000',
    address: 'Calle 123',
    province: 'Mendoza',
    postalCode: '5500',
    birthDate: '1990-01-01',
    email: 'buyer@example.com',
  },
  userNow: { email: 'auth@example.com' },
});
assert.equal(payload.tenant_id, 'tenant-a');
assert.equal(payload.event_slug, 'evento-1');
assert.equal(payload.sale_item_id, 99);
assert.equal(payload.buyer.email, 'auth@example.com');
assert.equal(payload.buyer.phone, '2615550000');

const reason = buildCheckoutBlockReason({
  selectedTicket: null,
  selectedEvent: { items: [] },
  hasCheckoutErrors: false,
});
assert.match(reason, /todavía no tiene tickets/i);

console.log('checkout helpers smoke: OK');
