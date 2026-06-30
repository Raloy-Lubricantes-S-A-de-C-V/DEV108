with open('motor_firmas/templates/motor_firmas/portal_dashboard.html', 'r') as f:
    content = f.read()

start_str = "    const defaultPayload = {"
end_str = "        } finally {\n            btn.disabled = false;\n            btn.innerHTML = '<span class=\"material-symbols-outlined text-[18px]\">play_arrow</span> Ejecutar Petición';\n        }\n    }"

start_idx = content.find(start_str)
end_idx = content.find(end_str, start_idx)

if start_idx != -1 and end_idx != -1:
    end_idx += len(end_str)
    
    new_js = """    let plantillasApiData = {{ plantillas_api|safe|default:"[]" }};

    function updateApiPayload() {
        const sel = document.getElementById('apiTemplateSelect');
        const viewInfo = document.getElementById('apiParamViewInfo').checked;
        const notif = document.getElementById('apiParamNotification').checked;
        const mobile = document.getElementById('apiParamMobile').checked;
        
        const templateId = sel.value;
        if (!templateId) {
            document.getElementById('apiPayload').value = '';
            return;
        }

        const template = plantillasApiData.find(p => p.id === templateId);
        if (!template) return;

        let payload = {
            "reference_id": "PRUEBA-API-" + Math.floor(Math.random() * 10000),
            "template_id": template.id,
            "document_variables": {},
            "firmantes": []
        };

        if(viewInfo) payload.view_info = "form";
        if(notif) payload.notification_enabled = true;
        if(mobile) payload.notified_to_mobile = true;

        (template.variables || []).forEach(v => {
            payload.document_variables[v] = "INGRESA TU VALOR AQUI";
        });

        (template.firmantes_config || []).forEach((f, i) => {
            payload.firmantes.push({
                "nombre": "Firmante " + (i + 1),
                "email": "firmante" + (i+1) + "@ejemplo.com"
            });
        });

        document.getElementById('apiPayload').value = JSON.stringify(payload, null, 2);
    }

    function openApiTester() {
        if(plantillasApiData.length > 0 && !document.getElementById('apiTemplateSelect').value) {
            document.getElementById('apiTemplateSelect').selectedIndex = 1;
        }
        updateApiPayload();
        document.getElementById('apiResponse').innerText = 'Esperando petición...';
        document.getElementById('apiResponse').style.color = '#a8a8a8';
        document.getElementById('apiResponse').style.backgroundColor = 'transparent';
        document.getElementById('apiModalOverlay').style.display = 'flex';
    }

    function closeApiTester() {
        document.getElementById('apiModalOverlay').style.display = 'none';
    }

    async function sendApiRequest() {
        const btn = document.getElementById('apiBtnSend');
        const responseBox = document.getElementById('apiResponse');
        let payloadStr = document.getElementById('apiPayload').value;
        let apiKey = document.getElementById('apiN8nKey').value.trim();
        let payloadObj;

        try {
            payloadObj = JSON.parse(payloadStr);
        } catch(e) {
            responseBox.innerText = "Error: El JSON no es válido.\\n\\n" + e.message;
            responseBox.style.color = '#ff6b6b';
            return;
        }

        if(!apiKey) {
            if(!confirm("No has ingresado un API Key. N8N podría rechazar la petición. ¿Deseas continuar?")) return;
        }

        btn.disabled = true;
        btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[18px]">sync</span> Enviando...';
        responseBox.innerText = "Ejecutando petición hacia N8N...";
        responseBox.style.color = '#d4d4d4';

        try {
            let headers = { 'Content-Type': 'application/json' };
            if(apiKey) headers['X-Api-Key'] = apiKey;

            const res = await fetch('https://n8n.raloy.com.mx/webhook/request-signature', {
                method: 'POST',
                headers: headers,
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
                responseBox.style.color = '#4ade80';
            } else {
                responseBox.style.color = '#ff6b6b';
                responseBox.innerText = "HTTP Error " + res.status + "\\n\\n" + responseBox.innerText;
            }
        } catch(error) {
            responseBox.innerText = "Error de conexión o de red.\\n\\n" + error.message;
            responseBox.style.color = '#ff6b6b';
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<span class="material-symbols-outlined text-[18px]">play_arrow</span> Ejecutar Petición N8N';
        }
    }

    async function generarApiKey() {
        try {
            const res = await fetch('/api/portal-action/generar_api_key/', { method: 'POST' });
            const data = await res.json();
            if(!res.ok) throw new Error(data.error || 'Error al generar la llave');
            
            document.getElementById('newApiKeyValue').value = data.api_key;
            document.getElementById('copyKeyStatus').classList.add('hidden');
            document.getElementById('newApiKeyModal').style.display = 'flex';

            const tbody = document.getElementById('apiKeysTableBody');
            const emptyRow = document.getElementById('emptyKeysRow');
            if(emptyRow) emptyRow.remove();

            const tr = document.createElement('tr');
            tr.className = 'hover:bg-surface-container-lowest transition-colors';
            tr.innerHTML = '<td class="px-4 py-3 font-mono text-xs font-bold text-text-main">' + data.masked + '</td><td class="px-4 py-3 text-text-muted text-xs">' + data.created_at + '</td>';
            tbody.appendChild(tr);

        } catch(error) {
            alert(error.message);
        }
    }

    function closeNewKeyModal() {
        document.getElementById('newApiKeyModal').style.display = 'none';
        document.getElementById('newApiKeyValue').value = '';
    }

    function copyNewKey() {
        const input = document.getElementById('newApiKeyValue');
        input.select();
        document.execCommand('copy');
        document.getElementById('copyKeyStatus').classList.remove('hidden');
    }"""
    
    content = content[:start_idx] + new_js + content[end_idx:]
    with open('motor_firmas/templates/motor_firmas/portal_dashboard.html', 'w') as f:
        f.write(content)
    print("Replaced JS")
else:
    print("Failed to replace JS")
