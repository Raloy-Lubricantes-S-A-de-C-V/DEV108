# Configuración de Google Drive para Resguardo de Archivos

## Descripción General

El sistema de firma digital ahora permite configurar carpetas específicas en Google Drive para guardar:
1. **Contratos Base**: Contratos plantilla con el patrón `Contrato_Base_<NOMBRE COMPLETO>.pdf`
2. **Formatos**: Documentos de formato que los usuarios crean
3. **PDFs Firmados**: Resultados de los procesos de firma de formularios
4. **PDFs de API**: Resultados de procesos iniciados por API

## Acceso a la Configuración

### 1. Ingresa al Panel de Administración
- URL: `https://dsign.raloy.com.mx/admin-dashboard/`
- Requiere sesión como Super Administrador

### 2. Ubicación en el Panel
En el panel de administración, busca la sección **"Configuración de Drive Resguardo"** en las herramientas de administrador.

## Campos a Configurar

### Carpeta Raíz de Formatos
- **ID de Google Drive**: El ID de la carpeta raíz que contiene todos los formatos
- **Valor por Defecto**: `1sCj-iPiNtyitSHz5O2Mv3KSDGZiDDgf0`
- **Descripción**: Carpeta principal de resguardo

### Carpeta Formatos
- **ID de Google Drive**: La carpeta donde se guardan los formatos creados
- **Valor por Defecto**: `1QAFVrdUC76S_xmwjgqxIyzk0tUMoLmk9`
- **Descripción**: Los archivos DOC/DOCX creados irán aquí

### PDFs Firmados de Formatos
- **ID de Google Drive**: La carpeta para PDFs resultado de firmas en formularios
- **Valor por Defecto**: `1uiTpBfXLjfOedTfdf7xdlQKEsv91YhyA`
- **Descripción**: Los PDFs generados después de completar un proceso de firma irán aquí

### PDFs Generados por API
- **ID de Google Drive**: La carpeta para PDFs generados programáticamente
- **Valor por Defecto**: `1GlACvY3TOOq6k3nZ7YNdRG2AqGvlUOvP`
- **Descripción**: Los PDFs creados mediante llamadas API irán aquí

### Contratos Base ⭐ NUEVO
- **ID de Google Drive**: La carpeta donde se guardan los contratos base
- **Valor por Defecto**: `1PEBBy7nhpqcgL4VG7bAfg2MRKq3vHwOB`
- **Descripción**: Los archivos `Contrato_Base_<NOMBRE>.pdf` irán en esta carpeta
- **Importante**: Este campo es obligatorio

## Cómo Obtener el ID de una Carpeta en Google Drive

1. Abre Google Drive (drive.google.com)
2. Navega a la carpeta deseada
3. En la URL, verás algo como:
   ```
   https://drive.google.com/drive/folders/1ABC2DEF3GHI4JKL5MNO6PQRS7TUV8WXY
   ```
4. El ID es la parte final: `1ABC2DEF3GHI4JKL5MNO6PQRS7TUV8WXY`

## Permisos Requeridos

### Cuenta APPS
- Debe tener acceso a todas las carpetas configuradas
- Debe poder leer y escribir archivos en todas las carpetas

### Usuarios Generales
- Pueden crear archivos en sus carpetas personales
- Los archivos creados se compartirán con la cuenta APPS
- N8N moverá o copiará los archivos a las carpetas de resguardo

## Flujo de Guardado de Archivos

### 1. Contratos Base
```
Usuario crea contrato base
    ↓
Se guarda en carpeta del usuario
    ↓
Se comparte con cuenta APPS
    ↓
N8N mueve/copia a: Carpeta de Contratos Base configurada
```

### 2. Formatos
```
Usuario crea formato
    ↓
Se guarda en carpeta del usuario
    ↓
Se comparte con cuenta APPS
    ↓
N8N mueve/copia a: Carpeta de FORMATOS configurada
```

### 3. PDFs de Firma
```
Proceso de firma se completa
    ↓
PDF se genera y se sube a N8N
    ↓
N8N lo guarda en: Carpeta de PDFs Firmados configurada
```

## Configuración en N8N

El sistema Django envía la siguiente información a los webhooks de N8N:

```json
{
  "storage_policy": "formatos_pdfs_v1",
  "root_folder_id": "...",
  "formatos_folder_id": "...",
  "pdfs_folder_id": "...",
  "api_pdfs_folder_id": "...",
  "contratos_base_folder_id": "...",
  "formatos_folder_name": "Formatos",
  "pdfs_folder_name": "PDFs",
  "contratos_base_folder_name": "Contratos_Base"
}
```

### Webhooks que reciben esta información:
1. **N8N_WEBHOOK_PREPARAR_DIR**: Para organizar estructura de carpetas
2. **N8N_WEBHOOK_FINALIZAR_PROCESO**: Para guardar PDF final
3. **N8N_WEBHOOK_SUBIR_PDF_USUARIO**: Para guardar PDFs de usuario
4. **N8N_WEBHOOK_DESCARGAR_PDF_DRIVE**: Para descargar PDFs

## Cambios Realizados

### Base de Datos
- Agregado campo `contratos_base_folder_id` al modelo `ConfiguracionDriveResguardo`
- Migración: `0020_configuraciondriveresguardo_contratos_base`

### Backend (Django)
- Nuevas funciones para obtener configuración de contratos base
- Payloads actualizados para incluir `contratos_base_folder_id` en todos los webhooks
- Endpoint de administración actualizado para guardar la configuración

### Frontend
- Campo de entrada en el panel de administración
- Validación de campo obligatorio
- Carga y guardado de configuración

## Pruebas

Para verificar que la configuración funciona:

1. Accede al panel de admin
2. Ingresa los IDs de las carpetas
3. Haz clic en "Guardar Drive"
4. Deberías ver: "Configuración Drive guardada."
5. Cuando se cree un nuevo formato o se complete una firma, los archivos deberían guardarse en las carpetas especificadas

## Solución de Problemas

### Los archivos no se guardan en la carpeta correcta
1. Verifica que los IDs de carpeta sean correctos
2. Verifica que la cuenta APPS tiene permisos en las carpetas
3. Revisa los logs de N8N para errores de permiso

### Algunos archivos se guardan, otros no
1. Puede deberse a permisos insuficientes
2. Verifica que todas las carpetas tengan permisos compartidos con APPS

### El campo "Contratos Base" no es obligatorio
1. Usa el valor por defecto: `1PEBBy7nhpqcgL4VG7bAfg2MRKq3vHwOB`
2. O proporciona tu propio ID de carpeta

## Valores por Defecto

Si deseas restaurar los valores por defecto, usa estos IDs:

```
Carpeta Raíz: 1sCj-iPiNtyitSHz5O2Mv3KSDGZiDDgf0
Formatos: 1QAFVrdUC76S_xmwjgqxIyzk0tUMoLmk9
PDFs Formatos: 1uiTpBfXLjfOedTfdf7xdlQKEsv91YhyA
PDFs API: 1GlACvY3TOOq6k3nZ7YNdRG2AqGvlUOvP
Contratos Base: 1PEBBy7nhpqcgL4VG7bAfg2MRKq3vHwOB
```

## Notas de Seguridad

- Solo superadministradores pueden cambiar esta configuración
- Los cambios se guardan en la base de datos
- Se aplican a nivel global para todo el sistema
- La cuenta APPS debe tener acceso perpetuo a estas carpetas
