# Análisis de Workflows N8N Existentes

## Workflows Encontrados (15 total)

### 1. Flujos Principales de Firma

#### ✅ El Cartero (Notificador de Turno de Firma)
- **Función**: Notifica al siguiente firmante que le toca firmar
- **Entrada**: Webhook con datos del firmante
- **Salida**: Email de notificación
- **Campos Drive**: `folder_id` (no crítico para Drive)

#### ✅ El Finalizador (Sube el PDF sellado y avisa a todos)
- **Función**: Sube PDF final y notifica a todos
- **Entrada**: Webhook con PDF y datos
- **Salida**: PDF en Drive + Emails
- **Campos Drive**: 
  - ✓ `pdfs_folder_id`
  - ✓ Fallback a `folder_id`
  - ✓ Fallback a `api_pdfs_folder_id`
  - ✓ Default: `1uiTpBfXLjfOedTfdf7xdlQKEsv91YhyA`
- **Línea crítica**: `"value": "={{ $node[\"Webhook1\"].json.body.pdfs_folder_id || $node[\"Webhook1\"].json.body.folder_id || $node[\"Webhook1\"].json.body.dir || $node[\"Webhook1\"].json.body.api_pdfs_folder_id || \"1uiTpBfXLjfOedTfdf7xdlQKEsv91YhyA\" }}"`
- **Estado**: ✓ YA SOPORTA pdfs_folder_id

#### ⚠️ Subir PDF de Usuario
- **Función**: Sube PDF generado por usuario
- **Entrada**: Webhook con PDF binario
- **Salida**: Archivo en Drive
- **Campos Drive**: 
  - `folder_id` (requiere)
  - **PROBLEMA**: Solo usa `folder_id`, no tiene fallbacks
- **Línea crítica**: `"value": "={{ $json.body.folder_id }}"`
- **NECESITA ACTUALIZACIÓN**: Agregar fallbacks como El Finalizador

### 2. Preparación de Estructura

#### ⚠️ Preparar Directorio
- **Función**: Crea carpeta "Documentos Firmados"
- **Entrada**: Webhook con doc_id
- **Salida**: Carpeta creada en Drive
- **Campos Drive**: 
  - `parent_folder`
- **Línea crítica**: `"value": "={{$('Webhook').item.json.body.parent_folder}}"`
- **Estado**: Básico, no optimizado

#### ⚠️ Preparar Directorio Drive Plantillas
- **Función**: Prepara estructura completa para plantillas (formatos + PDFs)
- **Entrada**: Webhook con configuración de carpetas
- **Salida**: Estructura lista en Drive
- **Campos normalizados**:
  - ✓ `root_folder_id`
  - ✓ `formatos_folder_id`
  - ✓ `pdfs_folder_id`
  - ✓ `formatos_folder_name`
  - ✓ `pdfs_folder_name`
  - ❌ **FALTA**: `contratos_base_folder_id`
- **NECESITA ACTUALIZACIÓN**: Agregar soporte para contratos_base_folder_id

### 3. Descargar y Manejar PDFs

#### ✅ Descargar PDF Drive
- **Función**: Descarga PDF de Drive para procesar
- **Entrada**: Webhook con file_id
- **Salida**: PDF descargado
- **Campos Drive**: Genérico, no específico

#### ✅ El Finalizador
- (Ya descrito arriba)

### 4. Análisis y Plantillas

#### ✅ Analizar Plantilla Docs
- **Función**: Analiza documento de Google Docs
- **Entrada**: Webhook con doc_id
- **Salida**: Análisis de estructura
- **Campos Drive**: `doc_id`

### 5. Notificaciones

#### ✅ El Cartero
- (Ya descrito arriba)

#### ✅ Invitar para firma
- **Función**: Invita usuario a firmar
- **Entrada**: Email del usuario
- **Salida**: Email de invitación

#### ✅ Enviar OTP Portal
- **Función**: Envía código OTP por email
- **Entrada**: Email, código
- **Salida**: Email con OTP

#### ✅ Notificaciones FIRMX
- **Función**: Notifica estado desde FIRMX
- **Entrada**: Webhook de FIRMX
- **Salida**: Actualización en sistema

#### ✅ Envia QR
- **Función**: Envía QR de trazabilidad
- **Entrada**: Datos del documento
- **Salida**: Email con QR

#### ✅ RECORDATORIO WP
- **Función**: Recordatorio por WhatsApp
- **Entrada**: Datos de firmante
- **Salida**: Mensaje WhatsApp

#### ✅ Owner
- **Función**: Notifica al propietario
- **Entrada**: Datos del proceso
- **Salida**: Notificaciones por email

#### ✅ Recuperación de PIN
- **Función**: Recupera PIN de firma
- **Entrada**: Email del usuario
- **Salida**: Email de recuperación

### 6. API

#### ✅ Recibe orden -> Crea PDF -> Manda a Django
- **Función**: Recibe solicitud, genera PDF, retorna a Django
- **Entrada**: Webhook con datos
- **Salida**: PDF generado
- **Campos Drive**: Varios

## Resumen de Hallazgos

### ✅ Lo que YA funciona correctamente:
1. El Finalizador: Soporta múltiples fallbacks para carpeta de PDFs
2. Preparar Directorio: Básico pero funcional
3. Notificaciones: Todas funcionan correctamente

### ⚠️ Lo que NECESITA actualización:

#### 1. **CRÍTICO**: Agregar soporte a `contratos_base_folder_id`
- Workflow "Preparar Directorio Drive Plantillas" - Línea 23
- Agregar campo a la normalización de solicitud
- Buscar/crear carpeta de contratos base

#### 2. **IMPORTANTE**: Mejorar "Subir PDF de Usuario"
- Actualmente solo usa `folder_id`
- Debería buscar fallbacks como El Finalizador
- Agregar soporte para múltiples tipos de carpeta

#### 3. **RECOMENDADO**: Crear nuevo workflow para Contratos Base
- Detectar archivos `Contrato_Base_*.pdf`
- Mover a carpeta `contratos_base_folder_id`
- Si no puede mover → Copiar
- Notificar resultado

## Campos que Django AHORA envía

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

## Plan de Actualización

### Fase 1: Actualizar Workflows Existentes
1. "Preparar Directorio Drive Plantillas" - Agregar contratos_base_folder_id
2. "Subir PDF de Usuario" - Agregar fallbacks

### Fase 2: Crear Nuevo Workflow
1. "Mover Contratos Base a Carpeta Resguardo" - Manejo de contratos base

### Fase 3: Validar
1. Probar todos los workflows
2. Verificar permisos de Drive
3. Verificar fallbacks
