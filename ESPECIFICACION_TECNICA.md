# Especificación Técnica Detallada

Este documento explica paso a paso el funcionamiento técnico del motor de firmas.

## 1. Modelado de Datos (MongoDB vía Djongo)

El sistema utiliza MongoDB con el conector `Djongo` para interactuar bajo el ORM de Django. 
- **`ProcesoFirma`**: Controla el ciclo de vida del documento (`PROCESSING`, `COMPLETED`, `CANCELLED`). Contiene la ruta al PDF, la lista JSON de `firmantes` y las variables solicitadas.
- **`PlantillaFormulario`**: Almacena las estructuras de los documentos detectadas por la IA de N8N. Resguarda los campos `variables` con sus respectivas `content-options`.
- **`DirectorioFirmas`**: Control de identidades. Almacena contraseñas hasheadas (`pin_hash`), firmas Base64 y asocia al usuario con un `tecnico_asignado` y `permisos_portal`.

> **Nota Técnica sobre Djongo:** El conector tiende a guardar arreglos JSON como cadenas de texto (`String`). En `views.py` se ha implementado una técnica de deserialización recursiva (`json.loads`) respaldada por bloques `try/except` para prevenir fallos al mapear arreglos guardados como Strings por el ORM.

## 2. Detección de Formularios Dinámicos

La vista `vista_firma_ui` intersecta `document_variables` (lo que le toca llenar al usuario) con la `PlantillaFormulario` original.
- Si un campo tiene `type: "option"` o `type: "seleccionable"`, el sistema carga su arreglo interno y expone a la vista HTML un objeto renderizable como `<select>`.
- El sistema incluye un mapeo de etiquetas (`labels_map`) que evita que el frontend muestre nombres técnicos (ej. `LEVEL_POSTION`), sustituyéndolos por lenguaje humano ("Nivel de Puesto").

## 3. Estampado en PDF (PyMuPDF / Fitz)

El archivo `motor_firmas/utils.py` contiene dos funciones maestras:

1. **`estampar_variables_en_pdf`**: Utiliza Expresiones Regulares Multilínea (`re.DOTALL`) para identificar etiquetas como `{{VAR}}` o `{{VAR:OPCION1_OPCION2}}` sin importar si Google Docs las fracturó con saltos de línea debido al estrechamiento de columnas. Se aplica un `redact_annot` (borrado total) de la etiqueta en el documento y se sobreescribe con el valor ingresado por el usuario usando la fuente Hebo/Helvetica.
2. **`estampar_firma_en_pdf`**: Soporta dos vías:
   - *Por búsqueda:* Encuentra etiquetas `{{FIRMA_X}}` y pinta la imagen Base64 del usuario allí.
   - *Por coordenadas absolutas:* Provenientes del editor visual (Drag & Drop) `portal_configurar_pdf.html`. Traduce porcentajes dinámicos (x/y) a coordenadas precisas de acuerdo a la escala y la página actual (`coordenadas.page`).

## 4. API Webhooks (N8N)

El sistema ofrece un *API Tester* directamente en el portal de usuarios. Todas las comunicaciones a servicios externos, como el envío final a N8N u obtención de carpetas de Drive, cuentan con un `timeout` definido y manejan códigos de estado HTTP para prevenir que la plataforma se quede colgando ante una caída de los microservicios externos.