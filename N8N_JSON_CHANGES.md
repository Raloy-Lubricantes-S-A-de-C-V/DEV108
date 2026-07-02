# Cambios JSON Específicos para Workflows N8N

## 1. Preparar Directorio Drive Plantillas - Cambio de Código

### Ubicación
**Nodo**: "Normalizar Solicitud" (línea ~23)
**Tipo**: n8n-nodes-base.code

### Código COMPLETO a reemplazar

**ANTES** (líneas 22-23 en el JSON):
```javascript
const body = $json.body || {};
let payload = body;
if (typeof body.data === 'string') {
  try { payload = JSON.parse(body.data); } catch (error) { payload = body; }
}
const root = String(payload.root_folder_id || payload.parent_folder || payload.folder_id || '1sCj-iPiNtyitSHz5O2Mv3KSDGZiDDgf0').trim();
const formatosFolderId = String(payload.formatos_folder_id || payload.formatos_id || payload.templates_folder_id || '').trim();
const pdfsFolderId = String(payload.pdfs_folder_id || payload.pdf_folder_id || payload.firmados_folder_id || payload.carpeta_firmados_id || '').trim();
const formatosName = String(payload.formatos_folder_name || payload.move_doc_to || 'Formatos').trim();
const pdfsName = String(payload.pdfs_folder_name || payload.pdf_target_folder || 'PDFs').trim();
const docId = String(payload.doc_id || payload.template_id || '').trim();
const pdfFileId = String(payload.pdf_file_id || payload.drive_file_id || payload.file_id || '').trim();
const quoteDrive = (value) => String(value || '').replace(/'/g, "\\'");
return [{
  json: {
    status: 'received',
    root_folder_id: root,
    parent_folder: root,
    formatos_folder_id: formatosFolderId,
    pdfs_folder_id: pdfsFolderId,
    formatos_folder_name: formatosName,
    pdfs_folder_name: pdfsName,
    doc_id: docId,
    pdf_file_id: pdfFileId,
    storage_policy: payload.storage_policy || 'formatos_pdfs_v1',
    accion: payload.accion || '',
    dry_run: !!payload.dry_run,
    formatos_query: `'${quoteDrive(root)}' in parents and mimeType = 'application/vnd.google-apps.folder' and name = '${quoteDrive(formatosName)}' and trashed = false`,
    pdfs_query: `'${quoteDrive(root)}' in parents and mimeType = 'application/vnd.google-apps.folder' and name = '${quoteDrive(pdfsName)}' and trashed = false`
  }
}];
```

**DESPUÉS** (agregar soporte para contratos base):
```javascript
const body = $json.body || {};
let payload = body;
if (typeof body.data === 'string') {
  try { payload = JSON.parse(body.data); } catch (error) { payload = body; }
}
const root = String(payload.root_folder_id || payload.parent_folder || payload.folder_id || '1sCj-iPiNtyitSHz5O2Mv3KSDGZiDDgf0').trim();
const formatosFolderId = String(payload.formatos_folder_id || payload.formatos_id || payload.templates_folder_id || '').trim();
const pdfsFolderId = String(payload.pdfs_folder_id || payload.pdf_folder_id || payload.firmados_folder_id || payload.carpeta_firmados_id || '').trim();
const contratosBaseFolderId = String(payload.contratos_base_folder_id || '1PEBBy7nhpqcgL4VG7bAfg2MRKq3vHwOB').trim();
const formatosName = String(payload.formatos_folder_name || payload.move_doc_to || 'Formatos').trim();
const pdfsName = String(payload.pdfs_folder_name || payload.pdf_target_folder || 'PDFs').trim();
const contratosBaseName = String(payload.contratos_base_folder_name || 'Contratos_Base').trim();
const docId = String(payload.doc_id || payload.template_id || '').trim();
const pdfFileId = String(payload.pdf_file_id || payload.drive_file_id || payload.file_id || '').trim();
const quoteDrive = (value) => String(value || '').replace(/'/g, "\\'");
return [{
  json: {
    status: 'received',
    root_folder_id: root,
    parent_folder: root,
    formatos_folder_id: formatosFolderId,
    pdfs_folder_id: pdfsFolderId,
    contratos_base_folder_id: contratosBaseFolderId,
    formatos_folder_name: formatosName,
    pdfs_folder_name: pdfsName,
    contratos_base_folder_name: contratosBaseName,
    doc_id: docId,
    pdf_file_id: pdfFileId,
    storage_policy: payload.storage_policy || 'formatos_pdfs_v1',
    accion: payload.accion || '',
    dry_run: !!payload.dry_run,
    formatos_query: `'${quoteDrive(root)}' in parents and mimeType = 'application/vnd.google-apps.folder' and name = '${quoteDrive(formatosName)}' and trashed = false`,
    pdfs_query: `'${quoteDrive(root)}' in parents and mimeType = 'application/vnd.google-apps.folder' and name = '${quoteDrive(pdfsName)}' and trashed = false`,
    contratos_base_query: `'${quoteDrive(root)}' in parents and mimeType = 'application/vnd.google-apps.folder' and name = '${quoteDrive(contratosBaseName)}' and trashed = false`
  }
}];
```

### JSON diff
```diff
+ const contratosBaseFolderId = String(payload.contratos_base_folder_id || '1PEBBy7nhpqcgL4VG7bAfg2MRKq3vHwOB').trim();
+ const contratosBaseName = String(payload.contratos_base_folder_name || 'Contratos_Base').trim();
  
+ contratos_base_folder_id: contratosBaseFolderId,
+ contratos_base_folder_name: contratosBaseName,
+ contratos_base_query: `'${quoteDrive(root)}' in parents and mimeType = 'application/vnd.google-apps.folder' and name = '${quoteDrive(contratosBaseName)}' and trashed = false`
```

---

## 2. Subir PDF de Usuario - Cambio de Fallback

### Ubicación
**Nodo**: "Subir a Drive" (tipo: n8n-nodes-base.googleDrive)
**Parámetro**: folderId

### Cambio específico

**Buscar en el JSON**:
```json
"name": "Subir a Drive",
"parameters": {
  "folderId": {
    "__rl": true,
    "value": "={{ $json.body.folder_id }}",
    "mode": "id"
  }
}
```

**Reemplazar con**:
```json
"name": "Subir a Drive",
"parameters": {
  "folderId": {
    "__rl": true,
    "value": "={{ $json.body.pdfs_folder_id || $json.body.folder_id || $json.body.api_pdfs_folder_id || $json.body.formatos_folder_id || '1uiTpBfXLjfOedTfdf7xdlQKEsv91YhyA' }}",
    "mode": "id"
  }
}
```

### JSON diff
```diff
- "value": "={{ $json.body.folder_id }}"
+ "value": "={{ $json.body.pdfs_folder_id || $json.body.folder_id || $json.body.api_pdfs_folder_id || $json.body.formatos_folder_id || '1uiTpBfXLjfOedTfdf7xdlQKEsv91YhyA' }}"
```

---

## 3. El Finalizador - SIN CAMBIOS

Este workflow ya está correctamente configurado. **No requiere cambios**.

Línea 17 ya contiene:
```json
"value": "={{ $node[\"Webhook1\"].json.body.pdfs_folder_id || $node[\"Webhook1\"].json.body.folder_id || $node[\"Webhook1\"].json.body.dir || $node[\"Webhook1\"].json.body.api_pdfs_folder_id || \"1uiTpBfXLjfOedTfdf7xdlQKEsv91YhyA\" }}"
```

---

## 4. Nuevo Workflow - Mover Contratos Base

**Archivo**: `Firma Digital _ Mover Contratos Base a Resguardo.json`

Este archivo ya está creado y listo para importar.

### Configuración requerida en N8N

1. Importar el archivo JSON
2. Verificar credenciales de Google Drive (deben estar disponibles)
3. Activar el workflow
4. Probar con un webhook POST a: `https://n8n.raloy.com.mx/webhook/mover-contratos-base`

### Payload de prueba
```json
{
  "file_id": "TEST_FILE_ID",
  "file_name": "Contrato_Base_Juan_Perez.pdf",
  "contratos_base_folder_id": "1PEBBy7nhpqcgL4VG7bAfg2MRKq3vHwOB",
  "source_folder": "FOLDER_ID"
}
```

---

## Checklist de Cambios

- [ ] Abrir "Preparar Directorio Drive Plantillas"
- [ ] Encontrar nodo "Normalizar Solicitud"
- [ ] Reemplazar código JavaScript (agregar líneas de contratos_base)
- [ ] Guardar cambios
- [ ] Abrir "Subir PDF de Usuario"
- [ ] Encontrar nodo "Subir a Drive"
- [ ] Actualizar parámetro folderId con fallbacks
- [ ] Guardar cambios
- [ ] Importar nuevo workflow "Mover Contratos Base"
- [ ] Activar nuevo workflow
- [ ] Probar cambios
- [ ] Verificar logs de éxito/error

---

## Líneas de Entrada/Salida de Datos

### Entrada (desde Django)
```json
{
  "contratos_base_folder_id": "1PEBBy7nhpqcgL4VG7bAfg2MRKq3vHwOB",
  "contratos_base_folder_name": "Contratos_Base",
  "formatos_folder_id": "1QAFVrdUC76S_xmwjgqxIyzk0tUMoLmk9",
  "formatos_folder_name": "Formatos",
  "pdfs_folder_id": "1uiTpBfXLjfOedTfdf7xdlQKEsv91YhyA",
  "pdfs_folder_name": "PDFs",
  "api_pdfs_folder_id": "1GlACvY3TOOq6k3nZ7YNdRG2AqGvlUOvP"
}
```

### Salida (al completarse)
```json
{
  "status": "success",
  "file_id": "ID_DEL_ARCHIVO",
  "file_name": "NOMBRE_DEL_ARCHIVO",
  "target_folder": "ID_CARPETA_DESTINO",
  "operation": "move_or_copy"
}
```

