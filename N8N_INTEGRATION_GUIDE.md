# Instrucciones para N8N - Manejo de Carpetas de Drive

## Resumen de Cambios

El sistema Django ahora envía la información de carpetas de resguardo a todos los webhooks de N8N. Esta información incluye un nuevo campo: `contratos_base_folder_id`.

## Información Enviada a N8N

En todos los payloads que Django envía a N8N, ahora están incluidos estos campos:

```json
{
  "contratos_base_folder_id": "1PEBBy7nhpqcgL4VG7bAfg2MRKq3vHwOB",
  "formatos_folder_id": "ID_CARPETA_FORMATOS",
  "pdfs_folder_id": "ID_CARPETA_PDFS",
  "api_pdfs_folder_id": "ID_CARPETA_API_PDFS",
  "root_folder_id": "ID_CARPETA_RAIZ",
  "formatos_folder_name": "Formatos",
  "pdfs_folder_name": "PDFs",
  "contratos_base_folder_name": "Contratos_Base"
}
```

## Webhooks Impactados

Los siguientes webhooks ahora reciben esta información adicional:

1. **N8N_WEBHOOK_PREPARAR_DIR**
   - URL: `/webhook/preparar-directorio2`
   - Uso: Prepara la estructura de carpetas para una plantilla
   - Debe usar: `contratos_base_folder_id`, `formatos_folder_id`, `pdfs_folder_id`

2. **N8N_WEBHOOK_FINALIZAR_PROCESO**
   - URL: `/webhook/subir-pdf-final`
   - Uso: Guarda el PDF final completado
   - Debe usar: `pdfs_folder_id` para guardar en carpeta de PDFs

3. **N8N_WEBHOOK_SUBIR_PDF_USUARIO**
   - URL: `/webhook/subir-pdf-usuario`
   - Uso: Guarda PDFs subidos por usuarios
   - Debe usar: `pdfs_folder_id` para guardar en carpeta correcta

4. **N8N_WEBHOOK_DESCARGAR_PDF_DRIVE**
   - URL: `/webhook/descargar-pdf-drive`
   - Uso: Descarga PDFs del Drive
   - Puede usar: Cualquier ID de carpeta según necesidad

## Tareas por Hacer en N8N

### 1. Flujo de Contratos Base
**Escenario**: Un usuario crea un contrato base `Contrato_Base_Juan_Perez.pdf`

**Proceso esperado**:
1. Usuario crea el archivo en su carpeta personal
2. Usuario comparte con cuenta APPS
3. N8N detecta el nuevo archivo
4. N8N verifica el nombre (debe iniciar con "Contrato_Base_")
5. N8N mueve/copia el archivo a: `contratos_base_folder_id`

**Campos disponibles en el webhook**:
- `contratos_base_folder_id`: ID de carpeta de destino
- `contratos_base_folder_name`: Nombre de la carpeta

### 2. Flujo de Formatos
**Escenario**: Un usuario crea un formato DOC/DOCX

**Proceso esperado**:
1. Usuario crea el documento en su carpeta personal
2. Usuario comparte con cuenta APPS
3. N8N detecta el nuevo documento
4. N8N verifica que sea un formato válido
5. N8N mueve/copia el archivo a: `formatos_folder_id`

**Campos disponibles en el webhook**:
- `formatos_folder_id`: ID de carpeta de destino
- `formatos_folder_name`: Nombre de la carpeta ("Formatos")

### 3. Flujo de PDFs Firmados
**Escenario**: Se completa un proceso de firma

**Proceso esperado**:
1. Django genera el PDF final
2. Django envía webhook a N8N con el PDF
3. N8N recibe el PDF y la información de carpeta
4. N8N guarda el PDF en: `pdfs_folder_id` (o `carpeta_firmados_id` si se especifica)
5. El nombre debe ser: `{reference_id}_CERTIFICADO.pdf`

**Campos disponibles en el webhook**:
- `pdfs_folder_id`: ID de carpeta de destino
- `pdfs_folder_name`: Nombre de la carpeta ("PDFs")
- `reference_id`: ID del proceso de firma

## Lógica Recomendada

### Si no puede mover, copie
```
INTENTA:
  Mover archivo desde carpeta_usuario a carpeta_destino
  
SI FALLA (error de permiso):
  COPIA archivo de carpeta_usuario a carpeta_destino
  MANTIENE nombre original del archivo
```

### Preferencia de carpeta
```
SI el webhook especifica: carpeta_firmados_id
  USA: carpeta_firmados_id
SINO SI el webhook especifica: pdfs_folder_id
  USA: pdfs_folder_id
SINO
  USA: pdfs_folder_name para buscar carpeta por nombre
```

## Pruebas en N8N

Para probar que la información se está recibiendo correctamente:

1. En N8N, agrega un nodo "Debug" después de recibir el webhook
2. Verifica que contenga los campos:
   - `contratos_base_folder_id`
   - `formatos_folder_id`
   - `pdfs_folder_id`
   - `api_pdfs_folder_id`
   - `contratos_base_folder_name`

3. Ejemplo de verificación:
```javascript
// En un nodo de código
if (!$input.item.json.contratos_base_folder_id) {
  throw new Error('Falta contratos_base_folder_id en el payload');
}
console.log('ID de contratos base:', $input.item.json.contratos_base_folder_id);
```

## Valores por Defecto

Si N8N no recibe alguno de estos valores, usa estos por defecto:

```
Carpeta Raíz: 1sCj-iPiNtyitSHz5O2Mv3KSDGZiDDgf0
Formatos: 1QAFVrdUC76S_xmwjgqxIyzk0tUMoLmk9
PDFs Formatos: 1uiTpBfXLjfOedTfdf7xdlQKEsv91YhyA
PDFs API: 1GlACvY3TOOq6k3nZ7YNdRG2AqGvlUOvP
Contratos Base: 1PEBBy7nhpqcgL4VG7bAfg2MRKq3vHwOB
```

## Cambios Requeridos en N8N

Los workflows en N8N necesitan ser revisados/actualizados para:

1. ✓ **Recibir** el nuevo campo `contratos_base_folder_id` en todos los webhooks
2. ✓ **Usar** `contratos_base_folder_id` cuando se procesen contratos base
3. ✓ **Usar** `formatos_folder_id` cuando se procesen formatos
4. ✓ **Usar** `pdfs_folder_id` cuando se procesen PDFs
5. ✓ **Validar** que la cuenta APPS tiene permisos en las carpetas especificadas

## Referencia de Campos Django

Para actualizar los workflows de N8N, busca estos valores en los payloads:

```javascript
// Contratos Base (NUEVO)
payload.contratos_base_folder_id
payload.contratos_base_folder_name

// Formatos
payload.formatos_folder_id
payload.formatos_folder_name

// PDFs Firmados
payload.pdfs_folder_id
payload.pdfs_folder_name

// PDFs API
payload.api_pdfs_folder_id

// Información General
payload.storage_policy      // "formatos_pdfs_v1"
payload.root_folder_id
```

## Ejemplo de Webhook Completo

Cuando Django envía a un webhook, el JSON completo incluirá:

```json
{
  "reference_id": "REF123456",
  "status": "COMPLETED",
  "pdf_final": "[contenido del PDF]",
  
  "storage_policy": "formatos_pdfs_v1",
  "root_folder_id": "1sCj-iPiNtyitSHz5O2Mv3KSDGZiDDgf0",
  "formatos_folder_id": "1QAFVrdUC76S_xmwjgqxIyzk0tUMoLmk9",
  "pdfs_folder_id": "1uiTpBfXLjfOedTfdf7xdlQKEsv91YhyA",
  "api_pdfs_folder_id": "1GlACvY3TOOq6k3nZ7YNdRG2AqGvlUOvP",
  "contratos_base_folder_id": "1PEBBy7nhpqcgL4VG7bAfg2MRKq3vHwOB",
  "formatos_folder_name": "Formatos",
  "pdfs_folder_name": "PDFs",
  "contratos_base_folder_name": "Contratos_Base",
  
  "folder_id": "1uiTpBfXLjfOedTfdf7xdlQKEsv91YhyA",
  "pdfs_folder_id": "1uiTpBfXLjfOedTfdf7xdlQKEsv91YhyA",
  
  "correos_destino": "email1@example.com,email2@example.com",
  "link": "https://dsign.raloy.com.mx/trazabilidad/..."
}
```

## Soporte

Si los archivos aún no se guardan correctamente después de hacer estos cambios:

1. Verifica los logs de N8N
2. Verifica que la cuenta APPS tiene acceso a las carpetas
3. Verifica que los IDs de carpeta son válidos
4. Contacta al equipo de desarrollo
