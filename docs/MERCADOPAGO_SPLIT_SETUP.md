# Configuración Mercado Pago Split (Develop -> Producción)

## 0) Referencia oficial

- Checkout Pro: configurar entorno de desarrollo
  - https://www.mercadopago.com.ar/developers/es/docs/checkout-pro/configure-development-enviroment#editor_6

Recomendación para **develop**:
- crear usuarios de prueba (vendedor/comprador) en Mercado Pago,
- usar credenciales de prueba de la app en develop,
- validar checkout completo antes de pasar credenciales de producción.


## 1) Crear app Marketplace en Mercado Pago

1. Entrar a [Mercado Pago Developers](https://www.mercadopago.com/developers/panel/app).
2. Crear una app nueva (tipo Marketplace).
3. Copiar credenciales de **Develop**:
   - Access Token.
   - Client ID.
   - Client Secret.
4. Configurar URL de OAuth Redirect para develop (ejemplo):
   - `https://develop.tu-dominio.com/oauth/callback`
5. Repetir para credenciales de **Producción**:
   - `https://tu-dominio.com/oauth/callback`

> En este proyecto el callback legacy `/oauth/callback` redirige a la lógica de `/api/payments/mp/oauth/callback`.

## 2) Variables de entorno requeridas

### Develop

```bash
MP_ACCESS_TOKEN=APP_USR-...-DEV
MP_API_BASE=https://api.mercadopago.com
MP_OAUTH_CLIENT_ID=1234567890
MP_OAUTH_CLIENT_SECRET=xxxxxxxx
MP_OAUTH_REDIRECT_URI=https://develop.tu-dominio.com/oauth/callback
SERVICE_CHARGE_PCT=0.15
```

### Producción

```bash
MP_ACCESS_TOKEN=APP_USR-...-PROD
MP_API_BASE=https://api.mercadopago.com
MP_OAUTH_CLIENT_ID=0987654321
MP_OAUTH_CLIENT_SECRET=yyyyyyyy
MP_OAUTH_REDIRECT_URI=https://tu-dominio.com/oauth/callback
SERVICE_CHARGE_PCT=0.15
```

## 3) Conectar vendedor (collector) por OAuth

1. Iniciar sesión como productor.
2. Ejecutar flujo OAuth desde front o por endpoint:
   - `GET /api/payments/mp/oauth/start?tenant=default`
3. El callback devuelve `user_id` del vendedor y persiste sus credenciales OAuth (`access_token`/`refresh_token`) en backend.
4. Guardar ese `user_id` en el evento como `mp_collector_id` y usar `settlement_mode=mp_split`.

## 4) Verificación técnica en develop

1. Estado de configuración:
   - `GET /api/payments/mp/split-health` (requiere sesión de productor/admin o header `x-producer` para entorno dev).
   - Debe devolver `ok=true` y todas las flags `has_*` en true.

   Ejemplo local:

```bash
curl -s -H "x-producer: dev" http://localhost:8000/api/payments/mp/split-health | jq
```
2. Verificación de preferencia sin cobrar:
   - `POST /api/payments/mp/create-preference?tenant=default&dry_run=true`
   - Body mínimo:

```json
{
  "order_id": "ORD-XXXXXXX"
}
```

3. Confirmar en respuesta:
   - `split_applied=true`.
   - `split_collector_id` con ID del vendedor.
   - `split_auth_mode = seller_access_token` (default actual).
   - Si `split_auth_mode = platform_token`, validar `preference.collector_id` y `preference.marketplace_fee`.

## 5) Paso a producción

1. Reemplazar credenciales develop por producción en variables del entorno productivo.
2. Actualizar `MP_OAUTH_REDIRECT_URI` al dominio productivo.
3. Reconectar vendedores en producción (OAuth de prod es independiente de develop).
4. Ejecutar nuevamente:
   - `GET /api/payments/mp/split-health`
   - `POST /api/payments/mp/create-preference?tenant=default&dry_run=true`
5. Ejecutar una compra real de bajo monto para validación final.
