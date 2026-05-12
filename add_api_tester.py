import sys

with open('motor_firmas/templates/motor_firmas/portal_dashboard.html', 'r') as f:
    content = f.read()

# 1. Add button
old_btns = '''            <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                {% if tiene_carpeta_dominio %}'''

new_btns = '''            <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                <button onclick="openApiTester()" class="btn-crear" style="background-color: #f39c12; border: none; cursor: pointer; color: white;">
                    <span>⚡</span> PROBAR API (WEBHOOK)
                </button>
                {% if tiene_carpeta_dominio %}'''

if old_btns in content:
    content = content.replace(old_btns, new_btns)
else:
    print("Warning: Could not find button insertion point.")

# 2. Add Modal CSS
old_style = '''    <style>'''

new_style = '''    <style>
        /* Modal API Tester */
        .api-modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(15, 23, 42, 0.75); z-index: 1000; justify-content: center; align-items: center; backdrop-filter: blur(4px); }
        .api-modal { background: #fff; width: 900px; max-width: 95%; height: 85vh; border-radius: 12px; display: flex; flex-direction: column; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.1), 0 10px 10px -5px rgba(0,0,0,0.04); overflow: hidden; }
        .api-header { background: #0f172a; color: #fff; padding: 15px 20px; display: flex; justify-content: space-between; align-items: center; }
        .api-header h2 { margin: 0; font-size: 1.25rem; font-weight: 600; display: flex; align-items: center; gap: 10px; }
        .api-header button { background: none; border: none; color: #cbd5e1; cursor: pointer; font-size: 1.5rem; transition: color 0.2s; }
        .api-header button:hover { color: #fff; }
        .api-body { display: flex; flex: 1; overflow: hidden; }
        .api-col { flex: 1; padding: 20px; display: flex; flex-direction: column; gap: 10px; overflow-y: auto; }
        .api-col:first-child { border-right: 1px solid #e2e8f0; background: #f8fafc; }
        .api-label { font-size: 0.85rem; font-weight: 700; color: #475569; text-transform: uppercase; letter-spacing: 0.5px; }
        .api-textarea { width: 100%; flex: 1; font-family: 'Courier New', Courier, monospace; font-size: 0.9rem; padding: 15px; border: 1px solid #cbd5e1; border-radius: 8px; box-sizing: border-box; resize: none; background: #1e293b; color: #e2e8f0; outline: none; box-shadow: inset 0 2px 4px rgba(0,0,0,0.1); }
        .api-textarea:focus { border-color: #3b82f6; }
        .api-btn-send { background: #10b981; color: white; border: none; padding: 12px 24px; border-radius: 6px; font-weight: 600; font-size: 1rem; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px; transition: background 0.2s; margin-top: 10px; }
        .api-btn-send:hover { background: #059669; }
        .api-btn-send:disabled { background: #94a3b8; cursor: not-allowed; }
        .api-response { flex: 1; background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 8px; padding: 15px; overflow-y: auto; font-family: 'Courier New', Courier, monospace; font-size: 0.85rem; color: #334155; margin: 0; white-space: pre-wrap; word-break: break-all; }
        .api-method-badge { background: #3b82f6; color: white; padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: bold; }
        .api-url { font-family: monospace; font-size: 0.9rem; color: #64748b; background: #e2e8f0; padding: 6px 12px; border-radius: 6px; margin-bottom: 10px; word-break: break-all; }'''

content = content.replace(old_style, new_style)

# 3. Add Modal HTML and JS at the end of body
old_body_end = '''</body>
</html>'''

new_body_end = '''
    <!-- API TESTER MODAL -->
    <div class="api-modal-overlay" id="apiModalOverlay">
        <div class="api-modal">
            <div class="api-header">
                <h2><span class="api-method-badge">POST</span> /webhook/request-signature</h2>
                <button onclick="closeApiTester()">×</button>
            </div>
            <div class="api-body">
                <!-- Request Column -->
                <div class="api-col">
                    <div class="api-url">https://n8n.raloy.com.mx/webhook/request-signature</div>
                    <label class="api-label">Payload JSON (Editable)</label>
                    <textarea class="api-textarea" id="apiPayload" spellcheck="false"></textarea>
                    <button class="api-btn-send" id="apiBtnSend" onclick="sendApiRequest()">
                        <span>▶</span> Ejecutar Petición
                    </button>
                </div>
                <!-- Response Column -->
                <div class="api-col" style="background: white;">
                    <label class="api-label">Respuesta del Servidor</label>
                    <pre class="api-response" id="apiResponse">Presiona "Ejecutar Petición" para ver el resultado...</pre>
                </div>
            </div>
        </div>
    </div>

    <script>
        const defaultPayload = {
          "reference_id": "CONTRATO-RALOY-2026-007",
          "template_id": "19U1b55WEqvPtQ6jAtn5_OrpMj_y8SgFGdKAk1N8HwqI",
          "document_variables": {
            "NOMBRE_EMPLEADO": "Alejandro Lopez Guzmán",
            "ID_NOMINA": "0000456",
            "MODELO_EQUIPO": "MacBook Air (M2, 2022)",
            "NUMERO_SERIE": "QW4RT5Y6U7I8",
            "FECHA_ENTREGA": "01 de Marzo de 2026"
          },
          "firmantes": [
            {
              "nombre": "Pedro Jimenez Blanquel",
              "email": "pjimenezb@raloy.com.mx"
            },
            {
              "nombre": "Alejandro Lopez Guzman",
              "email": "apps@raloy.com.mx"
            }
          ]
        };

        function openApiTester() {
            document.getElementById('apiPayload').value = JSON.stringify(defaultPayload, null, 2);
            document.getElementById('apiResponse').innerText = 'Esperando petición...';
            document.getElementById('apiResponse').style.color = '#334155';
            document.getElementById('apiResponse').style.backgroundColor = '#f1f5f9';
            document.getElementById('apiModalOverlay').style.display = 'flex';
        }

        function closeApiTester() {
            document.getElementById('apiModalOverlay').style.display = 'none';
        }

        async function sendApiRequest() {
            const btn = document.getElementById('apiBtnSend');
            const responseBox = document.getElementById('apiResponse');
            let payloadStr = document.getElementById('apiPayload').value;
            let payloadObj;

            try {
                payloadObj = JSON.parse(payloadStr);
            } catch(e) {
                responseBox.innerText = "Error: El JSON no es válido.\\n\\n" + e.message;
                responseBox.style.color = '#b91c1c';
                responseBox.style.backgroundColor = '#fee2e2';
                return;
            }

            btn.disabled = true;
            btn.innerHTML = '<span>⏳</span> Enviando...';
            responseBox.innerText = "Ejecutando petición hacia N8N...";
            responseBox.style.color = '#334155';
            responseBox.style.backgroundColor = '#f8fafc';

            try {
                const res = await fetch('https://n8n.raloy.com.mx/webhook/request-signature', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payloadObj)
                });
                
                const text = await res.text();
                let jsonRes;
                try { 
                    jsonRes = JSON.parse(text); 
                    responseBox.innerText = JSON.stringify(jsonRes, null, 2);
                } catch(e) { 
                    responseBox.innerText = text; 
                }

                if(res.ok) {
                    responseBox.style.color = '#047857';
                    responseBox.style.backgroundColor = '#d1fae5';
                    // Refrescar el grid del dashboard si la peticion tuvo exito
                    setTimeout(() => { if(typeof renderGrid === 'function') renderGrid(); }, 1500);
                } else {
                    responseBox.style.color = '#b91c1c';
                    responseBox.style.backgroundColor = '#fee2e2';
                    responseBox.innerText = `HTTP Error ${res.status}\\n\\n${responseBox.innerText}`;
                }
            } catch(error) {
                responseBox.innerText = "Error de conexión o de red.\\n\\n" + error.message;
                responseBox.style.color = '#b91c1c';
                responseBox.style.backgroundColor = '#fee2e2';
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<span>▶</span> Ejecutar Petición';
            }
        }
    </script>
</body>
</html>'''

content = content.replace(old_body_end, new_body_end)

with open('motor_firmas/templates/motor_firmas/portal_dashboard.html', 'w') as f:
    f.write(content)

print("Template updated successfully.")
