# Prompt Maestro — Frontend TicketPro (análisis completo + blueprint)

## 1) Auditoría funcional completa del frontend actual

### 1.1 Arquitectura general de UI
- **SPA React** con un núcleo principal en `App.jsx` (archivo monolítico con lógica de vistas públicas, checkout, productor, administrador/staff, validación QR y POS).  
- **Navegación por estado interno (`view`) + soporte de hash/path** para flujos especiales (ej. checkout/success, accesos staff).  
- **Diseño visual consistente**: dark premium, glassmorphism, acento índigo/fucsia, tipografía en mayúsculas con alto contraste.

### 1.2 Header / navegación global
- Header fijo con branding **TicketPro**, CTA de login/logout y tabs principales:
  - **Cartelera**
  - **Mis Tickets**
  - **Administrador** (solo staff)
- Doble comportamiento responsive: tabs desktop y tabs mobile.
- Protección de rutas de UX:
  - Si usuario no autenticado intenta entrar a Mis Tickets => abre modal de login y vuelve a público.

### 1.3 Home (Cartelera pública)
- Carga eventos desde `/api/public/events?tenant=default`.
- Filtros de **ciudad**, **categoría** y **búsqueda textual**.
- Solo muestra eventos `visibility=public`.
- Módulo de destacados con carrusel auto-scroll (`FeaturedCarousel`) y precio “Desde ...”.
- Cards con:
  - flyer (fallback robusto)
  - categoría/ciudad
  - título
  - fecha
  - precio desde mínimo ticket
  - badge/estado sold out (si aplica).

### 1.4 Detalle de evento
- Apertura desde slug con carga combinada:
  - `/api/public/events/{slug}`
  - `/api/public/sale-items?tenant=default&event_slug={slug}`
- Incluye:
  - información completa de evento
  - tickets/sale items
  - selección de cantidad
  - share del evento
  - mapa/ubicación y utilidades de navegación
  - compatibilidad de normalización de distintos payloads legacy.

### 1.5 Checkout (flujo de compra)
- Validaciones front estrictas de datos obligatorios:
  - nombre y apellido
  - DNI
  - domicilio
  - provincia
  - código postal
  - fecha de nacimiento
  - teléfono
  - aceptación de términos
- Cálculo de service charge con porcentaje configurable del evento.
- Creación de orden vía `/api/orders/create`.
- Si pago Mercado Pago:
  - crea preferencia `/api/payments/mp/create-preference`
  - redirige a checkout externo MP
  - maneja retorno `/checkout/success`.
- Estado de éxito con polling/reintento suave y guía al usuario para ver activos en Mis Tickets.

### 1.6 Mis Tickets (cliente)
- Carga activos del usuario desde `/api/orders/my-assets`.
- Soporta activos de entradas y consumos/barra.
- Filtros por tipo/estado/fecha/búsqueda.
- Funciones clave:
  - ver QR
  - descargar QR
  - descargar PDF de tickets
  - reenvío por email
  - iniciar solicitud de cancelación
  - transferir orden a otro usuario
- Manejo de cache de QR y estados de carga/error.

### 1.7 Panel de Productor
- Vista “producer” con:
  - listado de eventos del productor
  - dashboard por evento
  - edición/creación de eventos
  - gestión de tickets/sale items
  - gestión de vendedores
  - operaciones POS
  - cortesías
  - reporting comercial
  - audiencia/campañas (marketing).

#### 1.7.1 Editor de evento (modal/wizard)
- Wizard para evento nuevo:
  - Paso info base
  - Ubicación/flyer
  - Tickets/Vendedores
  - Confirmación
- Campos y datos requeridos relevantes:
  - title
  - slug (autogenerado)
  - start_date/start_time
  - city / venue / address
  - lat / lng
  - description
  - payout_alias
  - cuit
  - settlement_mode (`manual_transfer` o `mp_split`)
  - mp_collector_id (si split)
  - accept_terms
- Carga de flyer con preview local + upload backend.
- Integración OAuth Mercado Pago para conectar collector ID.

#### 1.7.2 Tickets / Sale Items
- CRUD completo (crear, editar precio/stock, activar/pausar, borrar).
- Validaciones de duplicados por nombre.
- Compatibilidad con endpoints producer y admin.
- Manejo de errores de dominio (`forbidden_event`, `duplicate key`, etc.).

#### 1.7.3 Sellers (vendedores)
- CRUD de vendedores por evento.
- Toggle activo/pausado.
- Validaciones de código único.
- Soporte “draft local” cuando backend no permite persistir aún.

#### 1.7.4 POS / Taquilla
- Emisión de venta en puerta por `sale_item_id`:
  - método de pago
  - seller_code
  - datos de comprador opcionales
- Emisión de cortesías por ticket.
- Resultado con order_id, tickets emitidos y acciones:
  - PDF
  - envío por mail
  - compartir por WhatsApp.

#### 1.7.5 Analítica y reporting
- Dashboard producer con KPIs + series.
- Listados de tickets vendidos, ventas de barra y ventas por vendedor.
- Export CSV con columnas de buyer/order/ticket.
- Resumen de revenue tickets + bar.

#### 1.7.6 Marketing
- Segmentación de audiencia por:
  - evento
  - rango de fechas
  - sale_item
  - búsqueda
- Export de audiencia.
- Campañas:
  - crear
  - listar
  - ver detalle
  - enviar
  - ver entregas.

### 1.8 Panel Administrador (supportAI/staff)
- Gateado por `supportAiStatus.is_staff`.
- Dashboard admin global:
  - KPIs multievento
  - listado de eventos
  - delete requests pendientes
- Operaciones admin:
  - crear evento para owner
  - transferir evento a otro owner
  - pausar/reactivar evento
  - gestionar evento como admin (tickets/sellers)
  - revisar/atender solicitudes de eliminación
  - cancelar tickets en contexto admin
  - ver ventas barra por evento
  - filtros complejos de reporte por productor/estado/liquidación/orden.

### 1.9 Staff links + QR Validator + Staff POS
- Links staff por evento con modos controlados.
- Validador QR:
  - input manual o scanner
  - endpoint `/api/orders/validate`
  - token staff por header
  - feedback inmediato de validación.
- Staff POS:
  - venta rápida operativa para personal autorizado.

### 1.10 Footer
- Footer legal/comercial completo con:
  - links legales (Términos, Privacidad, Reembolsos)
  - FAQs cliente y productor
  - contacto por emails
  - WhatsApp
  - redes
  - nota de marca registrada y derechos.

### 1.11 Login/Auth UX
- Modal de login con Google + opción email link.
- Persistencia de sesión por cookies/credenciales incluidas en fetch.
- Logout dedicado.
- Comportamiento contextual según acción pendiente (ej. checkout/myTickets/producer).

### 1.12 Robustez técnica de frontend
- Normalización defensiva de payloads legacy (nombres de campos alternativos).
- Fallback de imágenes y saneo de URLs.
- Error boundaries para modales complejos.
- Múltiples estados de loading/error y protección doble-click en operaciones críticas.
- Compatibilidad responsive en vistas principales.

---

## 2) Estilo visual actual de TicketPro (guía de diseño)

### 2.1 ADN visual
- **Base oscura premium** (`bg-[#050508]`, capas negras translúcidas).
- **Acento principal índigo/violeta** (`indigo-500/600`) con sombras luminosas.
- **Glassmorphism**: fondos `bg-white/5`, bordes `border-white/10`, `backdrop-blur`.
- **Tipografía display**: títulos en uppercase, heavy/black, itálica para marca.

### 2.2 Componentes visuales
- Botones en cápsula/redondeados (`rounded-2xl`, `rounded-3xl`).
- Tarjetas elevadas con blur y bordes sutiles.
- Header fijo translúcido con blur.
- Inputs claros en tema oscuro con alto contraste y focus ring índigo.

### 2.3 Interacción
- Feedback inmediato en hover/active.
- Mensajes de error y alertas humanas.
- Microtransiciones cortas y consistentes.
- Señalética fuerte para estados críticos (sold out, errores de modal, etc.).

---

## 3) Qué cambiar del front para que se vea “rotundamente distinto” sin perder funciones

1. **Nuevo sistema visual tokenizado**
   - Introducir design tokens (color, spacing, radius, shadows, motion) y theme switch (dark/light).
   - Mantener contratos funcionales y estructura de pantallas.

2. **Replantear layout macro**
   - Pasar de header + vistas largas a shell con sidebar contextual en producer/admin.
   - Mantener rutas, permisos y endpoints intactos.

3. **Componentización estricta**
   - Extraer bloques de `App.jsx` a módulos por dominio:
     - Public
     - Checkout
     - MyTickets
     - Producer
     - Admin
     - Staff Ops
   - Mantener la lógica actual pero desacoplada por capas.

4. **UI kit propio**
   - Crear componentes base (`Button`, `Input`, `Card`, `Modal`, `DataTable`, `Badge`, `Tabs`) con variantes.
   - Reemplazar clases repetidas sin cambiar comportamientos.

5. **Tablas y analytics “pro”**
   - Migrar listados admin/producer a tablas avanzadas con sorting, paginado, columnas configurables y export.

6. **Reforzar accesibilidad**
   - Foco visible consistente, labels y aria en modales, navegación teclado end-to-end.

7. **Motion + feedback modernizados**
   - Skeletons en cargas, toasts unificados, confirm dialogs consistentes.

8. **Performance / mantenibilidad**
   - Code splitting por vista, query caching (ej. React Query), y centralización de cliente API.

> Clave: cambiar la **capa de presentación y arquitectura interna**, nunca los contratos de datos ni reglas de negocio.

---

## 4) Prompt maestro (copiar/pegar para reconstruir frontend completo)

```txt
Actúa como un staff engineer de Frontend + Product Designer senior. 
Tu misión es rediseñar y reconstruir el frontend completo de TicketPro SIN perder ninguna funcionalidad existente.

### Objetivo principal
Crear un frontend moderno, altamente mantenible y escalable, que conserve al 100% los flujos actuales de negocio:
- Home/Cartelera pública
- Detalle de evento
- Checkout completo con Mercado Pago
- Mis Tickets (entradas + barra)
- Panel Productor (eventos, tickets, sellers, POS, cortesías, dashboard, reportes)
- Panel Administrador/Staff (dashboard global, gestión eventos, transferencias, reportes, delete requests)
- QR Validator + Staff POS
- Header + Footer + Legal
- Login Google/email-link y gestión de sesión

### Restricciones innegociables
1) No eliminar ninguna funcionalidad.
2) Mantener contratos de API y payloads actuales (incluyendo compat legacy de campos).
3) Mantener permisos/roles: público, usuario autenticado, productor, staff/admin.
4) Mantener flujos críticos: compra, emisión, validación, descarga/envío PDF, cancelaciones, transferencias.
5) Mantener responsive mobile-first.
6) Mantener fallback y robustez de errores.

### Stack esperado
- React + Vite
- TailwindCSS (o equivalente tokenizado)
- Estado por dominio (hooks + context o store ligero)
- Capa API centralizada
- Componentes reutilizables (UI Kit)

### Arquitectura objetivo
- src/modules/public
- src/modules/checkout
- src/modules/myTickets
- src/modules/producer
- src/modules/admin
- src/modules/staff
- src/shared/ui
- src/shared/api
- src/shared/utils

### Funcionalidades a implementar (checklist exhaustivo)
A. Header global
- Marca, navegación principal, login/logout, tabs contextual desktop/mobile.

B. Home/Cartelera
- Listado eventos públicos
- Filtros ciudad/categoría/búsqueda
- Carrusel destacados
- Cards con flyer, fecha, venue, ciudad, precio desde, estado sold-out

C. Detalle de evento
- Carga detalle + sale-items
- Selección ticket/cantidad
- Info extendida, mapa, compartir
- Control de stock/sold out

D. Checkout
- Form con validaciones estrictas: fullName, dni, address, province, postalCode, birthDate, phone, acceptTerms
- Cálculo service charge
- Crear orden
- Integración Mercado Pago preferencia + redirect
- Pantalla success y reconciliación post-pago

E. Mis Tickets
- Listado activos del usuario
- Filtros por tipo/estado/fecha/búsqueda
- Ver QR, descargar QR, descargar PDF, enviar PDF por mail
- Solicitar cancelación y transferir orden

F. Productor
- Listado eventos propios
- Dashboard por evento (KPIs, series)
- Editor evento (crear/editar):
  - title, slug, start_date, start_time, city, venue, address, lat, lng, description
  - payout_alias, cuit, settlement_mode, mp_collector_id
  - accept_terms
  - upload flyer con preview
- Tickets/sale-items CRUD completo
- Sellers CRUD completo
- POS venta en puerta
- Emisión de cortesías
- Reportes: sold tickets, bar orders, seller sales
- Export CSV
- Marketing: audience filters/export + campañas CRUD/send/deliveries

G. Administrador/Staff
- Dashboard global
- Listado eventos + filtros avanzados
- Crear evento para owner
- Transferir owner
- Pausar/reactivar eventos
- Gestionar tickets/sellers de cualquier evento
- Atender solicitudes de eliminación
- Cancelar tickets en modo admin
- Reportes multi-evento

H. Staff Operativo
- Staff links por evento
- QR validator (scanner + input manual)
- Staff POS con token y validaciones

I. Footer y legal
- Links legales configurables por env
- FAQ cliente/productor
- Contacto y redes
- Marca y derechos

### Diseño / estilo objetivo (renovado)
- Cambiar drásticamente la identidad visual respecto al frontend actual
- Definir design tokens (color, radius, spacing, typography, motion)
- Mantener accesibilidad AA
- Mantener consistencia en estados: loading, empty, error, success
- Crear patrones visuales claros por dominio (Public / Producer / Admin)

### Requisitos de calidad
- Type-safe en contratos internos (TS recomendado)
- Tests de UI críticos (checkout, login guard, compra, validación QR)
- Mocks y fixtures para escenarios sin backend
- Manejo robusto de errores API
- Zero regressions funcionales

### Entregables
1) Plan de migración por fases sin downtime.
2) Arquitectura de carpetas y responsabilidades.
3) UI Kit base con ejemplos.
4) Implementación completa por módulos.
5) Checklist final de paridad funcional (100%).
6) Documento de “qué se mantuvo igual y qué cambió visualmente”.

Comienza con:
- un inventario funcional detallado,
- mapa de rutas/vistas/roles,
- y luego entrega el plan de ejecución fase por fase.
```

---

## 5) Versión corta del prompt (para compartir rápido)

```txt
Rediseñá el frontend completo de TicketPro sin perder ninguna funcionalidad ni contrato API.
Debe incluir: cartelera pública, detalle evento, checkout MP, mis tickets, panel productor (eventos/tickets/sellers/POS/cortesías/reportes/marketing), panel admin staff (dashboard, gestión multievento, transferencias, delete requests, cancelaciones), validador QR y staff POS, header/footer/legal y auth.
Mantener robustez legacy y responsive.
Cambiar drásticamente el look&feel mediante design tokens + UI Kit + arquitectura modular por dominio.
Entregar plan por fases, implementación completa y checklist de paridad funcional 100%.
```
