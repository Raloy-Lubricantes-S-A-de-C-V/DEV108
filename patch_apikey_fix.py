import re

with open('motor_firmas/templates/motor_firmas/portal_dashboard.html', 'r') as f:
    content = f.read()

# 1. Enforce API Key
old_confirm = 'if(!apiKeyToUse) {\n            if(!confirm("No has ingresado un API Key válida. N8N podría rechazar la petición. ¿Deseas continuar?")) return;\n        }'
new_confirm = 'if(!apiKeyToUse) {\n            alert("Error: Es indispensable ingresar una API Key válida para autorizar la petición.");\n            return;\n        }'
if old_confirm in content:
    content = content.replace(old_confirm, new_confirm)
    print("Replaced API Key check")
else:
    print("Failed to replace API Key check")

# 2. Fix copyNewKey and generarApiKey
old_js = """    async function generarApiKey() {
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

new_js = """    async function generarApiKey() {
        try {
            const res = await fetch('/api/portal-action/generar_api_key/', { 
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCookie('csrftoken')
                }
            });
            let data;
            try {
                data = await res.json();
            } catch(jsonErr) {
                const text = await res.text();
                throw new Error("El servidor no devolvió una respuesta válida. Código: " + res.status + " | Info: " + text.substring(0, 50));
            }
            
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
            alert("Hubo un problema al generar la API Key: " + error.message);
        }
    }

    function closeNewKeyModal() {
        document.getElementById('newApiKeyModal').style.display = 'none';
        document.getElementById('newApiKeyValue').value = '';
    }

    function copyNewKey() {
        const input = document.getElementById('newApiKeyValue');
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(input.value).then(() => {
                document.getElementById('copyKeyStatus').classList.remove('hidden');
            }).catch(err => {
                input.select();
                document.execCommand('copy');
                document.getElementById('copyKeyStatus').classList.remove('hidden');
            });
        } else {
            input.select();
            document.execCommand('copy');
            document.getElementById('copyKeyStatus').classList.remove('hidden');
        }
    }"""

if old_js in content:
    content = content.replace(old_js, new_js)
    print("Replaced functions")
else:
    print("Failed to replace functions")

with open('motor_firmas/templates/motor_firmas/portal_dashboard.html', 'w') as f:
    f.write(content)
