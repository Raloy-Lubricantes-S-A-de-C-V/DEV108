# Guía de Actualización de Workflows N8N

## Workflow 1: Preparar Directorio Drive Plantillas (CRÍTICO)

### Cambios Necesarios

**Archivo**: `Firma Digital _ Preparar Directorio Drive Plantillas.json`

**Línea a modificar**: Aproximadamente línea 23 (Nodo "Normalizar Solicitud")

### Cambio en el código JavaScript

**ANTES** (línea ~23):
```javascript
const formatosName = String(payload.formatos_folder_name || payload.move_doc_to || 'Formatos').trim();
const pdfsName = String(payload.pdfs_folder_name || payload.pdf_target_folder || 'PDFs').trim();
```

**DESPUÉS** (agregar):
```javascript
const formatosName = String(payload.formatos_folder_name || payload.move_doc_to || 'Formatos').trim();
const pdfsName = String(payload.pdfs_folder_name || payload.pdf_target_folder || 'PDFs').trim();
const contratosBaseName = String(payload.contratos_base_folder_name || 'Contratos_Base').trim();
const contratosBaseFolderId = String(payload.contratos_base_folder_id || '').trim();
```

**Y agregar al return, después de `pdfs_query`**:
```javascript
contratos_base_folder_id: contratosBaseFolderId,
contratos_base_folder_name: contratosBaseName,
contratos_base_query: contratosBaseFolderId ? 
  `'${quoteDrive(root)}' in parents and mimeType = 'application/vnd.google-apps.folder' and name = '${quoteDrive(contratosBaseName)}' and trashed = false` 
  : ''
```

### Impacto
- El workflow ahora recibirá `contratos_base_folder_id` de Django
- Podrá buscar y crear la carpeta de contratos base si es necesaria
- Transmitirá la información a otros workflows

---

## Workflow 2: Subir PDF de Usuario (IMPORTANTE)

### Cambios Necesarios

**Archivo**: `Firma Digital _ Subir PDF de Usuario.json`

**Línea a modificar**: Aproximadamente línea 15 (Nodo "Subir a Drive", parámetro "folderId")

### Cambio en el valor de carpeta

**ANTES**:
```json
"value": "={{ $json.body.folder_id }}"
```

**DESPUÉS**:
```json
"value": "={{ $json.body.pdfs_folder_id || $json.body.folder_id || $json.body.api_pdfs_folder_id || $json.body.formatos_folder_id || \"1uiTpBfXLjfOedTfdf7xdlQKEsv91YhyA\" }}"
```

### Impacto
- El workflow ahora es más resiliente
- Si `folder_id` no viene, intentará usar `pdfs_folder_id`
- Tiene múltiples fallbacks
- Valor por defecto si no hay nada

---

## Workflow 3: Nuevo - Mover Contratos Base a Resguardo (NUEVO)

### ✅ COMPLETADO
**Archivo creado**: `Firma Digital _ Mover Contratos Base a Resguardo.json`

### Funcionalidad
- Recibe webhook con datos de contrato base
- Valida que sea formato `Contrato_Base_*.pdf`
- Intenta mover el archivo a la carpeta de resguardo
- Si falla, copia el archivo (fallback)
- Retorna resultado a Django

### Cómo usarlo
```bash
POST https://n8n.raloy.com.mx/webhook/mover-contratos-base
Content-Type: application/json

{
  "file_id": "ID_DEL_ARCHIVO",
  "file_name": "Contrato_Base_Juan_Perez.pdf",
  "contratos_base_folder_id": "1PEBBy7nhpqcgL4VG7bAfg2MRKq3vHwOB",
  "source_folder": "CARPETA_ORIGEN"
}
```

---

## Workflow 4: El Finalizador (YA ACTUALIZADO)

**Estado**: ✓ YA FUNCIONA CORRECTAMENTE

Este workflow ya soporta `pdfs_folder_id` gracias a su estructura con múltiples fallbacks:

```javascript
"value": "={{ $node[\"Webhook1\"].json.body.pdfs_folder_id || $node[\"Webhook1\"].json.body.folder_id || $node[\"Webhook1\"].json.body.dir || $node[\"Webhook1\"].json.body.api_pdfs_folder_id || \"1uiTpBfXLjfOedTfdf7xdlQKEsv91YhyA\" }}"
```

**No requiere cambios**.

---

## Pasos para Implementación

### Paso 1: Importar Nuevo Workflow
1. En N8N, click en "Import workflow"
2. Copiar contenido de `Firma Digital _ Mover Contratos Base a Resguardo.json`
3. Click "Import"
4. Activar el workflow

### Paso 2: Actualizar "Preparar Directorio Drive Plantillas"
1. Abrir el workflow en N8N
2. Click en el nodo "Normalizar Solicitud"
3. Agregar el código para `contratos_base_folder_id` (ver arriba)
4. Guardar

### Paso 3: Actualizar "Subir PDF de Usuario"
1. Abrir el workflow en N8N
2. Click en el nodo "Subir a Drive"
3. Editar el parámetro "folderId"
4. Reemplazar el valor (ver arriba)
5. Guardar

### Paso 4: Probar
1. Crear un contrato base: `Contrato_Base_Test.pdf`
2. Compartir con cuenta APPS
3. Verificar que se mueve a la carpeta de resguardo
4. Verificar que se copia si el movimiento falla

---

## Valores a Usar

```
Contratos Base Folder ID: 1PEBBy7nhpqcgL4VG7bAfg2MRKq3vHwOB
Contratos Base Folder Name: Contratos_Base
Formatos Folder ID: 1QAFVrdUC76S_xmwjgqxIyzk0tUMoLmk9
Formatos Folder Name: Formatos
PDFs Folder ID: 1uiTpBfXLjfOedTfdf7xdlQKEsv91YhyA
PDFs Folder Name: PDFs
API PDFs Folder ID: 1GlACvY3TOOq6k3nZ7YNdRG2AqGvlUOvP
```

---

## Validación Post-Cambios

### Checklist
- [ ] Importar nuevo workflow "Mover Contratos Base"
- [ ] Actualizar "Preparar Directorio Drive Plantillas"
- [ ] Actualizar "Subir PDF de Usuario"
- [ ] Probar movimiento de contrato base
- [ ] Probar copia como fallback (revokear permisos temporalmente)
- [ ] Probar subida de PDF de usuario
- [ ] Verificar que PDFs se guardan en carpeta correcta
- [ ] Verificar que formatos se guardan en carpeta correcta

---

## Notas Importantes

1. **Google Drive API**: Todos los workflows usan la API v3 de Google Drive
2. **Permisos**: La cuenta "Google Drive Aplicaciones Grupo Nova" debe tener acceso a todas las carpetas
3. **Fallbacks**: Los fallbacks son críticos para robustez
4. **Nombres de carpetas**: Deben coincidir exactamente (case-sensitive en algunos casos)
5. **IDs de archivo**: Siempre validar que el archivo_id sea válido antes de operaciones

---

## Rollback (Si algo falla)

1. Desactivar el nuevo workflow
2. Revertir cambios en los workflows actualizados (usar git/backup)
3. Verificar que todo vuelve a funcionar
4. Contactar al equipo de desarrollo

