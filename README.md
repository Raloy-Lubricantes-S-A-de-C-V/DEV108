# Sistema de Certificación Digital y Gestión de Firmas - Raloy

Bienvenido al sistema automatizado de certificación de documentos y firmas electrónicas. Esta plataforma centraliza y orquesta el flujo de firmas de documentos corporativos, permitiendo desde el estampado de firmas autógrafas/PIN hasta la recolección de formularios dinámicos incrustados en los PDFs (plantillas basadas en Google Docs).

## 🚀 Funcionamiento General

El sistema actúa como el motor central que interactúa con flujos automatizados (N8N) y los usuarios finales. Su flujo de vida es el siguiente:

1. **Recepción del Documento:** N8N genera un PDF (ya sea libre o desde una plantilla de Google Docs) y lo envía al sistema vía API (`/api/recibir-documento/`).
2. **Interpretación Dinámica:** Si el documento proviene de una plantilla de formulario, el motor busca la configuración en la base de datos para construir un formulario en tiempo real, transformando etiquetas (ej. `{{OFFICE:SI_NO}}`) en listas desplegables legibles y estéticas.
3. **Certificación Segura:** Los usuarios reciben un enlace único de un solo uso por correo. Ingresan al portal y validan su identidad (ya sea con PIN corporativo o dibujando su firma).
4. **Estampado y Paginación:** El sistema incrusta la firma y las opciones seleccionadas directamente en las hojas correctas del documento original, soportando PDFs multipágina y detectando coordenadas dinámicas.
5. **Cierre de Ciclo:** Una vez recabadas todas las firmas en secuencia, el documento es sellado con SHA-256, se agregan hojas de auditoría y se retorna a N8N garantizando que **solo se comparta con cuentas de dominio interno**.

## 👥 Roles y Permisos (Administración)

- **Usuarios Enrolados (Firmantes):** Interfaz para firmar y llenar campos.
- **Técnicos (Administradores Base):** Tienen acceso al portal de administración, pero *sólo* pueden visualizar los documentos y empleados que el Superadmin les asigne.
- **Superadministradores:** Control maestro. Pueden enrolar técnicos, gestionar cualquier documento de la empresa, depurar usuarios y modificar configuraciones globales.

## 📄 Documentación Extendida

Para comprender a fondo la arquitectura, el código y las medidas de seguridad del sistema, consulta los siguientes documentos:

- 📖 **[Especificación Técnica Detallada](ESPECIFICACION_TECNICA.md)** - Diagrama del flujo a nivel de código, modelos de datos y manejo de PyMuPDF.
- 🛡️ **[Justificación de Robustez y Seguridad](JUSTIFICACION_ROBUSTEZ.md)** - Análisis de vulnerabilidades resueltas, manejo estricto de errores, política de correos internos y tokens de un solo uso.

---
*Desarrollado y mantenido para la infraestructura interna de la organización.*
