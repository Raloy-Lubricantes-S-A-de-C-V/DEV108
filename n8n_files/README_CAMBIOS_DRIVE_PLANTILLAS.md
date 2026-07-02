# Cambios Drive / n8n para plantillas y PDFs

## Archivos n8n actualizados/agregados

1. `Firma Digital _ El Finalizador (Sube el PDF sellado y avisa a todos).json`
   - Webhook: `subir-pdf-final`.
   - Ahora sube el PDF final a:
     - `pdfs_folder_id`, si viene en el payload.
     - si no viene, `folder_id`.
     - si no viene, `dir`.
     - ultimo fallback: `1sCj-iPiNtyitSHz5O2Mv3KSDGZiDDgf0`.
   - Ahora responde a Django:
     - `file_id`
     - `drive_file_id`
     - `pdf_file_id`
     - `webViewLink`

2. `Firma Digital _ Preparar Directorio Drive Plantillas.json`
   - Webhook nuevo: `preparar-directorio`.
   - Recibe `root_folder_id`, `doc_id`, `pdf_file_id`, `formatos_folder_name`, `pdfs_folder_name`.
   - Crea o localiza `Formatos` y `PDFs` dentro de la raiz.
   - Mueve el Google Doc de plantilla a `Formatos`.
   - Si recibe `pdf_file_id`, mueve ese PDF a `PDFs`.
   - Responde:
     - `root_folder_id`
     - `formatos_folder_id`
     - `pdfs_folder_id`

3. `Firma Digital _ Descargar PDF Drive.json`
   - Webhook nuevo: `descargar-pdf-drive`.
   - Recibe `file_id`, `drive_file_id` o `pdf_file_id`.
   - Descarga el PDF desde Drive y lo responde como binario `application/pdf`.
   - Django lo guarda temporalmente en `media/descargas`.

## Workflow que falta exportar/revisar en n8n

No existe en `n8n_files` el export de `request-signature`, por eso no se pudo editar directamente en JSON.
En n8n debes abrir el workflow que tenga el webhook:

```text
POST /webhook/request-signature
```

Y validar estos puntos:

1. Cuando el payload venga con `exec = form`, el PDF generado desde plantilla debe usar:

```text
pdfs_folder_id
```

como carpeta destino de PDFs. No debe usar `formatos_folder_id` ni `drive_folder_id` para guardar PDFs.

2. El Google Doc de plantilla viene en:

```text
template_id
```

Ese documento ya queda movido por `preparar-directorio` a `Formatos`.

3. Cuando `request-signature` mande el PDF generado a Django, en desarrollo debe apuntar a:

```text
http://10.150.4.250:8099/api/recibir-documento/
```

El servidor Django debe estar arriba con:

```bash
python3 manage.py runserver 10.150.4.250:8099 --settings=signature_project.settings
```

4. La llamada a Django debe ser `multipart/form-data`:

Campo archivo:

```text
pdf_file = PDF generado desde plantilla
```

Campo texto:

```text
data = JSON.stringify({...})
```

El JSON minimo debe conservar:

```json
{
  "reference_id": "FOLIO",
  "firmantes": [],
  "view_info": "file",
  "summary_data": {},
  "owner": "usuario@dominio.com",
  "dir": "ID_DE_PDFS",
  "exec": "form",
  "variables_asignadas": {}
}
```

Si `request-signature` tambien sube el PDF inicial a Drive, debe guardarlo en `pdfs_folder_id` y agregar en `summary_data`:

```json
{
  "drive_file_id": "ID_DEL_PDF_EN_DRIVE"
}
```

## Lo que no se debe cambiar

- `subir-pdf-usuario` se queda como esta: PDFs libres usan carpeta por dominio.
- FIRMX no entra en esta reorganizacion.
- No mover PDFs libres a `1sCj-iPiNtyitSHz5O2Mv3KSDGZiDDgf0`.

## Reorganizar lo existente

Primero probar:

```bash
python3 manage.py organizar_drive_resguardo --dry-run --settings=signature_project.settings
```

Si se ve correcto:

```bash
python3 manage.py organizar_drive_resguardo --settings=signature_project.settings
```

Este comando solo toca plantillas y procesos `exec=form`; no toca libres ni FIRMX. Los PDFs historicos solo se mueven si el proceso ya tiene guardado `drive_file_id`, `pdf_file_id`, `drive_final_file_id` o `file_id`.

## Limpieza de temporales

Para limpiar PDFs temporales descargados a `media/descargas`:

```bash
python3 manage.py limpiar_media_descargas --days 1 --settings=signature_project.settings
```
