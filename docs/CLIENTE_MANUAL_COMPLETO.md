# Manual del Cliente — Ticketera Entradas

## 1. Objetivo del documento
Este manual está pensado para usuarios finales y equipos operativos del cliente (producción, ventas y atención), con foco en:

- funcionalidades disponibles en la app,
- pasos de uso por rol,
- buenas prácticas operativas,
- resolución rápida de dudas frecuentes.

---

## 2. Qué es Ticketera Entradas
Ticketera Entradas es una plataforma para publicar eventos, vender entradas online y gestionar tickets digitales.

### Roles principales
- **Comprador/a:** navega eventos, compra entradas y administra sus tickets.
- **Productor/a:** crea eventos, configura entradas, vendedores y monitorea ventas.
- **Soporte/Operaciones:** asiste en incidencias de login, compra, pagos y tickets.

---

## 3. Funcionalidades en detalle

## 3.1 Portal público (catálogo de eventos)
Permite a cualquier visitante:
- Ver listado de eventos públicos.
- Filtrar por categorías.
- Abrir detalle de un evento.
- Ver tickets disponibles, precios y stock.

**Comportamiento esperado:**
- Solo se muestran eventos activos y públicos.
- Si un evento no tiene imagen principal, la app intenta mostrar una imagen alternativa configurada.

---

## 3.2 Registro / inicio de sesión
La app soporta dos vías:

### A) Login con Google
- El usuario valida su cuenta Google desde el modal de acceso.
- La sesión queda registrada para operar compras y “Mis tickets”.

### B) Login por email (magic link)
- El usuario ingresa email.
- Recibe un enlace temporal de acceso.
- Al abrir el enlace se completa la autenticación.

**Recomendación operativa:** ante reportes de “no llega el email”, revisar spam/promociones y confirmar que el correo esté bien escrito.

---

## 3.3 Compra de entradas
Flujo típico:
1. El comprador entra al detalle del evento.
2. Selecciona tipo y cantidad de entradas.
3. Completa sus datos de compra.
4. Paga mediante Mercado Pago.
5. Recibe confirmación y acceso a tickets (incluyendo PDF/QR según configuración).

**Resultados de compra esperados:**
- Orden creada en estado válido.
- Ticket(s) visibles en sección “Mis tickets”.
- Activos descargables (QR/PDF) disponibles.

---

## 3.4 Mis tickets / activos del comprador
El usuario autenticado puede:
- Ver historial de tickets.
- Descargar PDF de entradas.
- Visualizar o descargar QR.
- Enviar tickets por email (según configuración de entorno).
- Transferir una orden si corresponde a política operativa vigente.

---

## 3.5 Panel de productor

### Gestión de eventos
- Crear nuevo evento.
- Editar datos clave (título, fecha, venue, descripción, etc.).
- Activar/desactivar evento.
- Configurar flyer/imagen.

### Gestión de ítems de venta (entradas)
- Alta de ítems (nombre, precio, stock, tipo).
- Edición de precio/stock/estado.
- Baja lógica de ítems (desactivar o eliminar según endpoint).

### Punto de venta (taquilla)
- Registrar ventas presenciales de forma manual desde panel operativo.
- Cada venta de taquilla debe guardar medio de pago, operador y comprador (si se informa).
- La emisión de ticket/QR ocurre en el momento para no perder trazabilidad.

### Gestión de vendedores
- Alta y administración de vendedores/códigos.
- Edición de datos de vendedor.
- Eliminación de vendedores.

### Métricas de venta
- Vista dashboard del productor con consolidación de ventas.
- Endpoint público opcional de métricas por evento (protegido por clave pública del evento).

---

## 3.6 Pagos con Mercado Pago
La plataforma permite:
- Crear preferencia de pago.
- Confirmar/sincronizar el estado de orden tras el pago.
- Procesar notificaciones por webhook.

**Buenas prácticas para operación:**
- Verificar credenciales de MP por ambiente (test/prod).
- Confirmar `APP_BASE_URL` correcta para redirecciones.
- Mantener activo el webhook y su secreto en producción.

---

## 4. Manuales de uso (paso a paso)

## 4.1 Manual rápido del comprador
1. Entrar al catálogo de eventos.
2. Elegir evento y entradas.
3. Iniciar sesión (Google o email).
4. Completar compra y pagar.
5. Ir a “Mis tickets” para descargar/usar entradas.

### ¿Cómo usar el ticket en el acceso?
- Presentar QR desde celular o PDF impreso.
- Si hay problema de lectura, mostrar código/ID de orden a personal de validación.

---

## 4.2 Manual rápido del productor
1. Iniciar sesión con cuenta habilitada.
2. Crear evento con datos completos.
3. Cargar flyer.
4. Crear tipos de entradas (precio y stock).
5. Activar evento para publicación.
6. Monitorear ventas en dashboard.
7. Ajustar stock/precios según estrategia comercial.

### Checklist antes de publicar
- [ ] Fecha, lugar y horario correctos.
- [ ] Flyer visible.
- [ ] Precio final validado.
- [ ] Stock correcto por tipo de entrada.
- [ ] Evento activo y con visibilidad correcta.

---

## 4.3 Manual rápido de soporte operativo

### Incidencia: “No puedo iniciar sesión”
- Confirmar método (Google o email).
- Si es email, reintentar envío de magic link.
- Verificar que el usuario abra el último enlace recibido.

### Incidencia: “Pagó pero no ve tickets”
- Verificar estado de pago en MP.
- Ejecutar sincronización de orden.
- Revisar si la orden figura asociada al usuario autenticado correcto.

### Incidencia: “No me descarga el PDF”
- Probar endpoint de PDF por orden/ticket.
- Verificar bloqueos del navegador (popups/descargas).

### Incidencia: “No veo mi evento en catálogo”
- Confirmar evento activo.
- Confirmar tenant correcto.
- Revisar visibilidad (public/unlisted).

---

## 5. FAQ — TicketPro (clientes)

### 1) ¿Necesito una cuenta para comprar?
Sí. TicketPro requiere sesión activa para vincular tu compra con la sección “Mis tickets”.

### 2) ¿Puedo comprar varias entradas en una sola operación?
Sí, siempre que exista stock disponible en el tipo de entrada seleccionado.

### 3) ¿Dónde veo mis entradas después de pagar?
En “Mis tickets”. Desde allí podés abrir el QR y descargar el PDF cuando esté disponible.

### 4) ¿Qué hago si no me llega el email de acceso?
Revisá spam/promociones, esperá unos minutos y solicitá un nuevo enlace. Usá siempre el último correo recibido.

### 5) ¿Qué pasa si pagué y no veo tickets?
Puede existir una demora de sincronización. Si persiste, soporte debe validar el estado del pago y reintentar sync.

### 6) ¿Se puede transferir una compra?
Sí. La plataforma contempla transferencia de orden, sujeta a la política de cada evento.

### 7) ¿Cómo contacto a soporte de TicketPro?
Por email a `soporte@ticketpro.com.ar` o por WhatsApp oficial para casos urgentes.

### 8) ¿Cómo actualizo precio o stock de entradas?
Desde panel de productor → ítems de venta.

### 9) ¿Cómo oculto un evento sin borrarlo?
Desactivándolo o ajustando su visibilidad según necesidad operativa.

### 10) ¿La plataforma admite cupones/códigos de vendedores?
Sí. El módulo sellers/vendors permite gestionar códigos y seguimiento comercial.

### 11) ¿Qué hace el webhook de Mercado Pago?
Notifica pagos para actualizar el estado de órdenes y disparar automatizaciones asociadas.

### 12) ¿Puedo descargar tickets en PDF desde distintos dispositivos?
Sí, iniciando sesión con la misma cuenta asociada a la compra.

### FAQ rápido para productor (carga y panel)

#### 1) ¿Qué datos mínimos debe cargar un productor al crear un evento?
Título, fecha/hora, venue, descripción, flyer y al menos un ítem de venta con precio/stock.

#### 2) ¿Dónde se cargan los tipos de entradas y su stock?
En panel de productor → ítems de venta. Desde allí se crean categorías, precio y cupos por entrada.

#### 3) ¿Qué información puede ver en el panel de productor?
Listado de eventos, estado/visibilidad, ítems de venta, stock y vistas operativas de órdenes/tickets.

#### 4) ¿Cómo oculto un evento sin borrarlo?
Desactivándolo o cambiando su visibilidad para pausarlo temporalmente.

#### 5) ¿Cómo contacto a TicketPro para onboarding de productores?
Por `ventas@ticketpro.com.ar` y WhatsApp oficial.

---

## 6. Recomendaciones de operación para el cliente
- Definir un responsable diario de revisión de ventas e incidencias.
- Establecer un SLA interno para problemas de pago/ticketing.
- Mantener una base de respuestas cortas de soporte (copys) para WhatsApp/Instagram.
- Auditar semanalmente eventos activos, stocks y visibilidad.
- Antes de campañas grandes, testear un flujo de compra end-to-end.

---

## 7. Glosario rápido
- **Tenant:** partición lógica de datos por cliente/plataforma.
- **Sale item:** ítem vendible (entrada u otro concepto).
- **Order:** orden de compra.
- **Ticket asset:** archivo o recurso asociado a la entrada (PDF/QR).
- **Webhook:** notificación automática entre sistemas (ej. MP → Ticketera).
