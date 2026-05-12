# Justificación de Robustez y Análisis de Vulnerabilidades

Este documento detalla las precauciones de seguridad aplicadas al código para garantizar que la plataforma opere bajo estándares estrictos y evite fugas de información, manipulación de flujo o fallos ciegos.

## 1. Prevención de Fugas de Información (Capa Externa)

Una de las directrices primordiales de la plataforma es garantizar que **los documentos corporativos terminados jamás sean enviados a personal externo a la planta**, incluso si dicho personal fue invitado temporalmente a formar parte del flujo de firmas.

* **Solución Implementada:** En la función `procesar_firma`, justo al pasar al estado `COMPLETED`, el sistema agrupa todos los correos del documento (firmantes + dueño). Antes de inyectar esa lista a N8N, aplica un filtro de dominios permitidos (`dominios_permitidos`). Se toma el dominio originador (dueño del documento, ej. `@raloy.com.mx`) y explícitamente se rechaza cualquier correo con dominios ajenos.
* **Beneficio:** Mitiga por completo el riesgo de fuga de información clasificada a proveedores u observadores externos tras la finalización del contrato/solicitud.

## 2. Resiliencia contra Manipulación de UI y Envíos Incompletos

* **Solución Frontend:** El botón "Aceptar y Firmar" evalúa `input.value.trim()`. Si detecta campos vacíos o llenos de "espacios", frena la ejecución e ilumina con un marco rojo grueso los elementos faltantes.
* **Beneficio:** Evita que el usuario inyecte variables vacías en el backend y certifica que los datos impresos en el PDF estén íntegros.

## 3. Control de Estado y Firmas de Un Solo Uso (Single-Use Tokens)

El sistema impide que un documento firmado pueda volverse a firmar.
* **Solución:** Cada firmante posee un `token_firmante` único tipo UUID V4. En `vista_firma_ui`, se lee directamente de la base de datos si la propiedad `fecha_firma` ya está sellada. Si el atacante intenta acceder a la misma URL o re-enviar un POST simulado con su token, el sistema rechaza la visualización y rechaza la modificación en backend devolviendo "No es tu turno" o "Ya has firmado".
* **Beneficio:** Previene ataques de repetición (Replay Attacks).

## 4. Manejo Estricto de Errores (Cero Fallos Silenciosos)

Cualquier comportamiento imprevisto durante el estampado del PDF o la conexión final, se notifica explícitamente.
* **Solución Backend:** Se reemplazaron los genéricos `pass` o silencios en consola. En operaciones críticas, como contactar el Webhook de cierre, si N8N responde algo diferente a un HTTP 200, el sistema fuerza una interrupción (`raise Exception`), atrapa el hilo del error y devuelve al usuario final un código 500 con el mensaje literal del fallo y la instrucción de comunicarse con el área técnica.
* **Beneficio:** Otorga visibilidad real sobre incidencias de infraestructura o base de datos. Ningún documento quedará atrapado en el "limbo" de procesamiento sin que haya un registro formal del problema en la respuesta al cliente.

## 5. Blindaje del Superadministrador

* **Solución:** Se implementó una doble barrera para el administrador maestro. La evaluación de rol de superadmin no confía únicamente en la lectura de la base de datos (por si llegase a corromperse o un script forzara un apagado de `es_superadmin`), sino que también verifica por defecto las credenciales nativas del creador en el código (hardcoded check), evitando así los bloqueos administrativos accidentales (`admin_email == 'pjimenezb@raloy.com.mx'`).