import re
with open('motor_firmas/templates/motor_firmas/admin_usuarios_detalle.html', 'r') as f:
    content = f.read()

# Add the API Keys section just before the Preferencias de Notificación section
target_section = """    <section class="admin-module p-6 mb-5">
        <h2 class="text-xl font-bold text-primary border-b border-outline-variant pb-3 mb-5">Preferencias de Notificación</h2>"""

new_section = """    {% if 'api_tester' in permisos %}
    <section class="admin-module p-6 mb-5">
        <h2 class="text-xl font-bold text-primary border-b border-outline-variant pb-3 mb-5 flex items-center gap-2">
            <span class="material-symbols-outlined">api</span>
            API Keys de N8N
        </h2>
        <p class="text-sm text-text-muted mb-4">El usuario puede tener hasta 10 llaves API para sus integraciones. Como administrador puedes revocar accesos eliminando estas llaves.</p>
        
        <div class="overflow-x-auto border border-outline-variant rounded-lg mt-2">
            <table class="w-full text-left text-sm whitespace-nowrap bg-surface-container-lowest">
                <thead>
                    <tr class="text-xs font-bold text-primary uppercase bg-surface-container-low border-b border-outline-variant">
                        <th class="px-4 py-3">API Key (Enmascarada)</th>
                        <th class="px-4 py-3">Fecha de Creación</th>
                        <th class="px-4 py-3 text-right">Acción</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-outline-variant">
                    {% for k in usuario.api_keys %}
                    <tr class="hover:bg-surface-bright transition-colors">
                        <td class="px-4 py-3 font-mono text-xs font-bold text-text-main">{{ k.masked }}</td>
                        <td class="px-4 py-3 text-text-muted text-xs">{{ k.created_at }}</td>
                        <td class="px-4 py-3 text-right">
                            <button class="text-status-danger hover:text-white hover:bg-status-danger px-2 py-1 rounded transition-colors text-xs font-bold border border-status-danger inline-flex items-center gap-1" onclick="eliminarApiKey('{{ k.id }}')">
                                <span class="material-symbols-outlined text-[14px]">delete</span> Eliminar
                            </button>
                        </td>
                    </tr>
                    {% empty %}
                    <tr>
                        <td colspan="3" class="px-4 py-6 text-center text-text-muted italic text-xs">El usuario no tiene API Keys generadas.</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </section>
    {% endif %}

    <section class="admin-module p-6 mb-5">
        <h2 class="text-xl font-bold text-primary border-b border-outline-variant pb-3 mb-5">Preferencias de Notificación</h2>"""

if target_section in content:
    content = content.replace(target_section, new_section)
    print("Replaced admin html")
else:
    print("Failed to replace admin html")

js_target = """    function guardarCambios() {"""
js_new = """    function eliminarApiKey(keyId) {
        if(confirm("¿Estás seguro de que deseas eliminar esta API Key? Las integraciones que la utilicen dejarán de funcionar inmediatamente.")) {
            fetch('/api/admin-action/eliminar_api_key/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    usuario_id: {{ usuario.id }},
                    key_id: keyId
                })
            }).then(r => r.json()).then(res => {
                if(res.status === 'success') {
                    window.location.reload();
                } else {
                    alert("Error: " + res.error);
                }
            });
        }
    }

    function guardarCambios() {"""

if js_target in content:
    content = content.replace(js_target, js_new)
    print("Replaced admin js")
else:
    print("Failed to replace admin js")

with open('motor_firmas/templates/motor_firmas/admin_usuarios_detalle.html', 'w') as f:
    f.write(content)
print("Done patching admin")
