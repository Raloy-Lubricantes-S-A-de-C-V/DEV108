import re

with open('motor_firmas/templates/motor_firmas/portal_dashboard.html', 'r') as f:
    content = f.read()

# I will use regex or find to replace the <div class="api-modal-overlay"... to the end of the block.
start_idx = content.find('<div class="api-modal-overlay" id="apiModalOverlay">')
end_idx = content.find('{% endblock %}', start_idx)

if start_idx != -1 and end_idx != -1:
    new_html = """<div class="api-modal-overlay" id="apiModalOverlay" style="z-index: 50; display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6); align-items: center; justify-content: center; padding: 1rem;">
    <div class="api-modal w-full max-w-5xl bg-surface-container rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        <div class="bg-primary text-white px-6 py-4 flex justify-between items-center">
            <h2 class="text-lg font-bold flex items-center gap-3">
                <span class="bg-[#FFC107] text-black px-2 py-0.5 rounded text-xs font-black uppercase tracking-wider">POST</span> 
                /webhook/request-signature
            </h2>
            <button onclick="closeApiTester()" class="text-white/80 hover:text-white transition-colors">
                <span class="material-symbols-outlined">close</span>
            </button>
        </div>
        
        <div class="p-6 bg-surface-bright flex flex-col gap-6 overflow-y-auto">
            <!-- 1. Configuración -->
            <div class="bg-white p-5 rounded-xl border border-outline-variant shadow-sm space-y-5">
                <h3 class="text-primary font-bold text-base border-b border-outline-variant pb-2">1. Parámetros de la Petición</h3>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
                    <div>
                        <label class="block text-sm font-bold text-text-main mb-1">Plantilla a utilizar</label>
                        <select id="apiTemplateSelect" class="w-full px-3 py-2 border border-outline-variant rounded-lg bg-surface-container-lowest focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all" onchange="updateApiPayload()">
                            <option value="">-- Selecciona una plantilla --</option>
                            {% for p in plantillas_api %}
                            <option value="{{ p.id }}">{{ p.nombre }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm font-bold text-text-main mb-1">API Key de Autenticación (Header X-Api-Key)</label>
                        <input type="password" id="apiN8nKey" class="w-full px-3 py-2 border border-outline-variant rounded-lg bg-surface-container-lowest font-mono text-sm focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all" placeholder="rtk_...">
                    </div>
                </div>
                
                <div>
                    <label class="block text-sm font-bold text-text-main mb-2">Parámetros Adicionales (Metadatos)</label>
                    <div class="flex flex-wrap gap-5 text-sm">
                        <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" id="apiParamViewInfo" onchange="updateApiPayload()" class="h-4 w-4 rounded border-outline-variant text-primary focus:ring-primary"> Mostrar Formularios Previos</label>
                        <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" id="apiParamNotification" onchange="updateApiPayload()" class="h-4 w-4 rounded border-outline-variant text-primary focus:ring-primary"> Activar Notificaciones Email</label>
                        <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" id="apiParamMobile" onchange="updateApiPayload()" class="h-4 w-4 rounded border-outline-variant text-primary focus:ring-primary"> Notificar a App Móvil</label>
                    </div>
                </div>
            </div>

            <!-- 2. Test Area -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div class="flex flex-col h-full bg-[#1e1e1e] rounded-xl shadow-sm overflow-hidden border border-[#333]">
                    <div class="px-4 py-2 border-b border-[#333] flex justify-between items-center bg-[#252526]">
                        <span class="text-xs font-bold text-[#d4d4d4]">PAYLOAD JSON (EDITABLE)</span>
                    </div>
                    <textarea class="flex-grow p-4 font-mono text-xs bg-[#1e1e1e] text-[#d4d4d4] border-0 resize-none focus:ring-0 w-full min-h-[250px] outline-none" id="apiPayload" spellcheck="false"></textarea>
                    <div class="p-4 border-t border-[#333] bg-[#252526]">
                        <button class="w-full flex items-center justify-center gap-2 bg-transparent border border-[#d4d4d4] text-[#d4d4d4] font-bold py-2 rounded-lg hover:bg-white hover:text-black transition-colors" id="apiBtnSend" onclick="sendApiRequest()">
                            <span class="material-symbols-outlined text-[18px]">play_arrow</span>
                            Ejecutar Petición N8N
                        </button>
                    </div>
                </div>

                <div class="flex flex-col h-full bg-[#1e1e1e] rounded-xl shadow-sm overflow-hidden border border-[#333]">
                    <div class="px-4 py-2 border-b border-[#333] flex justify-between items-center bg-[#252526]">
                        <span class="text-xs font-bold text-[#d4d4d4]">RESPUESTA DEL SERVIDOR</span>
                    </div>
                    <pre class="flex-grow p-4 font-mono text-xs bg-[#1e1e1e] text-[#a8a8a8] overflow-auto w-full min-h-[250px] m-0" id="apiResponse">Esperando petición...</pre>
                </div>
            </div>

            <!-- 3. Gestión de API Keys -->
            <div class="bg-white p-5 rounded-xl border border-outline-variant shadow-sm">
                <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-outline-variant pb-4 mb-4">
                    <div>
                        <h3 class="text-primary font-bold text-base flex items-center gap-2">
                            <span class="material-symbols-outlined text-[18px]">key</span> Mis API Keys
                        </h3>
                        <p class="text-xs text-text-muted mt-1">Límite de 10 llaves por usuario. Utiliza estas llaves para autorizar tus peticiones hacia el API.</p>
                    </div>
                    <button onclick="generarApiKey()" class="shrink-0 flex items-center justify-center gap-2 border border-primary text-primary font-bold px-4 py-2 rounded-lg shadow-sm hover:bg-primary hover:text-white transition-all text-sm">
                        <span class="material-symbols-outlined text-[16px]">add</span> Nueva Llave
                    </button>
                </div>
                
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-sm whitespace-nowrap">
                        <thead>
                            <tr class="text-xs font-bold text-primary uppercase bg-surface-container-lowest border-b border-outline-variant">
                                <th class="px-4 py-3">API Key (Oculta)</th>
                                <th class="px-4 py-3">Creada el</th>
                            </tr>
                        </thead>
                        <tbody id="apiKeysTableBody" class="divide-y divide-outline-variant">
                            {% for k in api_keys %}
                            <tr class="hover:bg-surface-container-lowest transition-colors">
                                <td class="px-4 py-3 font-mono text-xs font-bold text-text-main">{{ k.masked }}</td>
                                <td class="px-4 py-3 text-text-muted text-xs">{{ k.created_at }}</td>
                            </tr>
                            {% empty %}
                            <tr id="emptyKeysRow">
                                <td colspan="2" class="px-4 py-6 text-center text-text-muted italic text-xs">No tienes API Keys generadas actualmente.</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- Modal Copiar Llave -->
<div id="newApiKeyModal" class="fixed inset-0 z-[60] hidden items-center justify-center bg-black/60 backdrop-blur-sm p-4">
    <div class="bg-white w-full max-w-md rounded-xl shadow-2xl overflow-hidden flex flex-col">
        <div class="px-5 py-4 border-b border-outline-variant bg-surface-bright flex items-center justify-between">
            <h3 class="font-bold text-primary flex items-center gap-2">
                <span class="material-symbols-outlined text-[20px] text-status-success">check_circle</span> ¡API Key Generada!
            </h3>
            <button type="button" onclick="closeNewKeyModal()" class="text-on-surface-variant hover:text-primary transition-colors">
                <span class="material-symbols-outlined">close</span>
            </button>
        </div>
        <div class="p-6">
            <div class="bg-[#FFF8E1] text-[#8F6D00] p-3 rounded-lg text-xs font-bold mb-4 flex gap-2 border border-[#FFE082]">
                <span class="material-symbols-outlined text-[18px]">warning</span>
                <p>Copia esta clave inmediatamente. Por tu seguridad, no volverá a mostrarse. Si la pierdes, deberás generar una nueva.</p>
            </div>
            <div class="relative">
                <input type="text" id="newApiKeyValue" readonly class="w-full pr-12 pl-4 py-3 border border-outline-variant rounded-lg bg-surface-container-lowest font-mono text-sm text-text-main focus:outline-none focus:border-primary">
                <button onclick="copyNewKey()" class="absolute right-2 top-1/2 -translate-y-1/2 text-primary hover:text-primary-container p-2 rounded-md hover:bg-surface-container transition-colors" title="Copiar al portapapeles">
                    <span class="material-symbols-outlined text-[18px]">content_copy</span>
                </button>
            </div>
            <div id="copyKeyStatus" class="text-xs font-bold text-status-success mt-2 hidden text-center">¡Copiada al portapapeles!</div>
        </div>
        <div class="px-6 py-4 bg-surface-bright border-t border-outline-variant text-right">
            <button type="button" onclick="closeNewKeyModal()" class="bg-primary hover:bg-primary-container text-white px-5 py-2 rounded-lg font-bold text-sm transition-colors">Cerrar</button>
        </div>
    </div>
</div>
"""
    content = content[:start_idx] + new_html + "\n" + content[end_idx:]
    
    with open('motor_firmas/templates/motor_firmas/portal_dashboard.html', 'w') as f:
        f.write(content)
    print("Replaced API tester html")
else:
    print("Failed to replace html")

