with open('motor_firmas/templates/motor_firmas/trazabilidad.html', 'r') as f:
    content = f.read()

old_btn = """                                {% if admin_can_resend %}
                                    <div class="pt-3">
                                        <button type="button"
                                                data-token="{{ proceso.token_acceso }}"
                                                data-firmante-token="{{ firmante.token_firmante|default:'' }}"
                                                data-email="{{ firmante.email }}"
                                                onclick="reenviarFirma(this)"
                                                class="inline-flex items-center justify-center gap-2 bg-secondary-container text-primary px-4 py-2 rounded-lg font-bold text-xs hover:bg-secondary-fixed-dim transition-colors">
                                            <span class="material-symbols-outlined text-[16px]">forward_to_inbox</span>
                                            Reenviar correo
                                        </button>
                                        <div class="resend-status text-xs font-bold mt-2"></div>
                                    </div>
                                {% endif %}"""

new_btn = """                                {% if admin_can_resend %}
                                    <div class="pt-3 flex flex-wrap items-center gap-2">
                                        <button type="button"
                                                data-token="{{ proceso.token_acceso }}"
                                                data-firmante-token="{{ firmante.token_firmante|default:'' }}"
                                                data-email="{{ firmante.email }}"
                                                onclick="reenviarFirma(this)"
                                                class="inline-flex items-center justify-center gap-2 bg-secondary-container text-primary px-4 py-2 rounded-lg font-bold text-xs hover:bg-secondary-fixed-dim transition-colors">
                                            <span class="material-symbols-outlined text-[16px]">forward_to_inbox</span>
                                            Reenviar correo
                                        </button>
                                        <button type="button"
                                                onclick="openWhatsappWizard('{{ firmante.whatsapp_link|escapejs }}', '{{ firmante.nombre|escapejs }}', '{{ firmante.email|escapejs }}')"
                                                class="inline-flex items-center justify-center gap-2 bg-[#25D366]/10 text-[#25D366] px-4 py-2 rounded-lg font-bold text-xs hover:bg-[#25D366]/20 transition-colors">
                                            <span class="material-symbols-outlined text-[16px]">forum</span>
                                            Notificar WhatsApp
                                        </button>
                                        <div class="resend-status text-xs font-bold mt-2 w-full"></div>
                                    </div>
                                {% endif %}"""

old_footer = """    <footer class="px-8 py-6 text-center border-t border-outline-variant">
        <p class="text-xs text-text-muted">© 2026 Raloy Lubricantes. Todos los derechos reservados.</p>
    </footer>
</div>
{% endblock %}"""

new_footer = """    <footer class="px-8 py-6 text-center border-t border-outline-variant">
        <p class="text-xs text-text-muted">© 2026 Raloy Lubricantes. Todos los derechos reservados.</p>
    </footer>
</div>

<!-- WhatsApp Wizard Modal -->
<div id="whatsappWizard" class="fixed inset-0 z-50 hidden items-center justify-center bg-black/60 backdrop-blur-sm p-4">
    <div class="bg-background-pure w-full max-w-md rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        <div class="px-6 py-4 border-b border-outline-variant bg-surface-bright flex items-center justify-between">
            <h3 class="text-xl font-bold text-[#25D366] flex items-center gap-2">
                <span class="material-symbols-outlined">forum</span> Notificar por WhatsApp
            </h3>
            <button type="button" onclick="closeWhatsappWizard()" class="text-on-surface-variant hover:text-primary transition-colors">
                <span class="material-symbols-outlined text-[24px]">close</span>
            </button>
        </div>
        <div class="p-6 overflow-y-auto space-y-4 text-text-main">
            <p class="text-sm font-medium">Destinatario: <span id="waName" class="font-bold text-primary"></span></p>
            <div>
                <label class="block text-sm font-bold text-text-main mb-1">Teléfono (con código de país, ej: +521234567890)</label>
                <input type="text" id="waPhone" class="w-full px-3 py-2 border border-outline-variant rounded-lg focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all" placeholder="+52...">
            </div>
            <div>
                <label class="block text-sm font-bold text-text-main mb-1">Enlace a enviar</label>
                <textarea id="waLink" readonly class="w-full px-3 py-2 border border-outline-variant rounded-lg bg-surface-container-low text-xs text-on-surface-variant outline-none resize-none h-20"></textarea>
            </div>
            <div id="waStatus" class="text-sm font-bold hidden"></div>
        </div>
        <div class="px-6 py-4 border-t border-outline-variant bg-surface-bright flex justify-end gap-3">
            <button type="button" onclick="closeWhatsappWizard()" class="px-4 py-2 rounded-lg font-bold text-sm text-text-muted hover:bg-outline-variant/30 transition-colors">Cancelar</button>
            <button type="button" id="waSendBtn" onclick="sendWhatsapp()" class="px-4 py-2 rounded-lg font-bold text-sm bg-[#25D366] text-white hover:bg-[#1DA851] transition-colors flex items-center gap-2">
                <span class="material-symbols-outlined text-[18px]">send</span> Enviar
            </button>
        </div>
    </div>
</div>
{% endblock %}"""

old_scripts = """    function toggleOriginalDocument() {
        const container = document.getElementById('originalDocumentContainer');
        if (container.classList.contains('hidden')) {
            container.classList.remove('hidden');
        } else {
            container.classList.add('hidden');
        }
    }
</script>"""

new_scripts = """    function toggleOriginalDocument() {
        const container = document.getElementById('originalDocumentContainer');
        if (container.classList.contains('hidden')) {
            container.classList.remove('hidden');
        } else {
            container.classList.add('hidden');
        }
    }

    let currentWaLink = '';

    function openWhatsappWizard(link, name, email) {
        if (!link) {
            alert("No hay enlace de firma disponible para este usuario.");
            return;
        }
        currentWaLink = link;
        document.getElementById('waName').textContent = name || email;
        document.getElementById('waPhone').value = '';
        document.getElementById('waLink').value = link;
        document.getElementById('waStatus').classList.add('hidden');
        document.getElementById('waSendBtn').disabled = false;
        document.getElementById('waSendBtn').innerHTML = '<span class="material-symbols-outlined text-[18px]">send</span> Enviar';
        document.getElementById('whatsappWizard').classList.remove('hidden');
        document.getElementById('whatsappWizard').classList.add('flex');
    }

    function closeWhatsappWizard() {
        document.getElementById('whatsappWizard').classList.add('hidden');
        document.getElementById('whatsappWizard').classList.remove('flex');
    }

    async function sendWhatsapp() {
        const phone = document.getElementById('waPhone').value.trim();
        if (!phone) {
            alert('Por favor ingresa un número de teléfono.');
            return;
        }

        const btn = document.getElementById('waSendBtn');
        const statusBox = document.getElementById('waStatus');
        btn.disabled = true;
        btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[18px]">sync</span> Enviando...';
        statusBox.classList.add('hidden');

        try {
            const url = 'https://n8n.raloy.com.mx/webhook/dsign-recordatorio-firma';
            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ numero: phone, url: currentWaLink })
            });

            if (!res.ok && res.type !== 'opaque') throw new Error('No se pudo enviar la notificación a N8N.');

            statusBox.textContent = '¡Notificación enviada correctamente!';
            statusBox.className = 'text-sm font-bold text-status-success';
            statusBox.classList.remove('hidden');
            setTimeout(closeWhatsappWizard, 2000);
        } catch (error) {
            statusBox.textContent = error.message;
            statusBox.className = 'text-sm font-bold text-status-danger mt-2';
            statusBox.classList.remove('hidden');
            btn.disabled = false;
            btn.innerHTML = '<span class="material-symbols-outlined text-[18px]">send</span> Reintentar';
        }
    }
</script>"""

if old_btn in content and old_footer in content and old_scripts in content:
    content = content.replace(old_btn, new_btn)
    content = content.replace(old_footer, new_footer)
    content = content.replace(old_scripts, new_scripts)
    with open('motor_firmas/templates/motor_firmas/trazabilidad.html', 'w') as f:
        f.write(content)
    print("Success replacing trazabilidad.html")
else:
    print("Failed to find old strings in trazabilidad.html")
    if old_btn not in content: print("old_btn not found")
    if old_footer not in content: print("old_footer not found")
    if old_scripts not in content: print("old_scripts not found")
