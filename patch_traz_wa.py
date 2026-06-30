import re
with open('motor_firmas/templates/motor_firmas/trazabilidad.html', 'r') as f:
    content = f.read()

# 1. Update the button call
old_button = "onclick=\"openWhatsappWizard('{{ firmante.whatsapp_link|escapejs }}', '{{ firmante.nombre|escapejs }}', '{{ firmante.email|escapejs }}')\""
new_button = "onclick=\"openWhatsappWizard('{{ proceso.token_acceso }}', '{{ firmante.token_firmante|default:'' }}', '{{ firmante.email|escapejs }}', '{{ firmante.whatsapp_link|escapejs }}', '{{ firmante.nombre|escapejs }}')\""

if old_button in content:
    content = content.replace(old_button, new_button)
    print("Replaced button call")
else:
    print("Could not find button call")

# 2. Add ultimo_reenvio_whatsapp display
old_history = """                                {% if firmante.ultimo_reenvio_correo %}
                                    <div class="text-xs text-on-surface-variant flex items-center gap-1 mt-2">
                                        <span class="material-symbols-outlined text-[14px]">mark_email_read</span>
                                        Reenviado el: {{ firmante.ultimo_reenvio_correo }}
                                    </div>
                                {% endif %}
                            {% endif %}"""

new_history = """                                {% if firmante.ultimo_reenvio_correo %}
                                    <div class="text-xs text-on-surface-variant flex items-center gap-1 mt-2">
                                        <span class="material-symbols-outlined text-[14px]">mark_email_read</span>
                                        Reenviado el: {{ firmante.ultimo_reenvio_correo }}
                                    </div>
                                {% endif %}
                                {% if firmante.ultimo_reenvio_whatsapp %}
                                    <div class="text-xs text-on-surface-variant flex items-center gap-1 mt-1">
                                        <span class="material-symbols-outlined text-[14px] text-[#25D366]">forum</span>
                                        WhatsApp: {{ firmante.ultimo_reenvio_whatsapp }} al {{ firmante.ultimo_telefono_whatsapp }}
                                    </div>
                                {% endif %}
                            {% endif %}"""

if old_history in content:
    content = content.replace(old_history, new_history)
    print("Replaced history display")
else:
    print("Could not find history display")

# 3. Update the Wizard UI
old_wizard_input = """            <div>
                <label class="block text-sm font-bold text-text-main mb-1">Teléfono (con código de país, ej: +521234567890)</label>
                <input type="text" id="waPhone" class="w-full px-3 py-2 border border-outline-variant rounded-lg focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all" placeholder="+52...">
            </div>"""

new_wizard_input = """            <div class="bg-secondary-container text-on-secondary-container p-3 rounded-lg text-xs font-bold border border-secondary/20 mb-2 flex gap-2">
                <span class="material-symbols-outlined text-[16px]">info</span>
                <p>No tenemos guardado el número telefónico, por lo que es indispensable que coloques el correcto para que le llegue el recordatorio.</p>
            </div>
            <div>
                <label class="block text-sm font-bold text-text-main mb-1">Teléfono (con código de país, ej: 521234567890)</label>
                <input type="text" id="waPhone" class="w-full px-3 py-2 border border-outline-variant rounded-lg focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all font-mono" placeholder="52...">
            </div>"""

if old_wizard_input in content:
    content = content.replace(old_wizard_input, new_wizard_input)
    print("Replaced wizard input")
else:
    print("Could not find wizard input")


# 4. Update the JS Logic
old_js = """    let currentWaLink = '';

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
    }"""

new_js = """    let currentWaLink = '';
    let currentWaToken = '';
    let currentWaFirmanteToken = '';
    let currentWaEmail = '';

    function openWhatsappWizard(token, firmanteToken, email, link, name) {
        if (!link) {
            alert("No hay enlace de firma disponible para este usuario.");
            return;
        }
        currentWaToken = token;
        currentWaFirmanteToken = firmanteToken;
        currentWaEmail = email;
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

        if (!confirm('¿Confirmas que el número ' + phone + ' es correcto? No lo tenemos guardado, por lo que es indispensable que sea el correcto para que le llegue el recordatorio.')) {
            return;
        }

        const btn = document.getElementById('waSendBtn');
        const statusBox = document.getElementById('waStatus');
        btn.disabled = true;
        btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[18px]">sync</span> Enviando...';
        statusBox.classList.add('hidden');

        try {
            const res = await fetch('/api/admin-action/notificar_whatsapp/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    token: currentWaToken,
                    firmante_token: currentWaFirmanteToken,
                    email: currentWaEmail,
                    telefono: phone,
                    link: currentWaLink
                })
            });

            const payload = await res.json();
            if (!res.ok) throw new Error(payload.error || 'No se pudo enviar la notificación de WhatsApp.');

            statusBox.textContent = '¡Notificación guardada y enviada correctamente!';
            statusBox.className = 'text-sm font-bold text-status-success';
            statusBox.classList.remove('hidden');
            setTimeout(() => {
                closeWhatsappWizard();
                window.location.reload();
            }, 1500);
        } catch (error) {
            statusBox.textContent = error.message;
            statusBox.className = 'text-sm font-bold text-status-danger mt-2';
            statusBox.classList.remove('hidden');
            btn.disabled = false;
            btn.innerHTML = '<span class="material-symbols-outlined text-[18px]">send</span> Reintentar';
        }
    }"""

if old_js in content:
    content = content.replace(old_js, new_js)
    print("Replaced JS Logic")
else:
    print("Could not find JS Logic")

with open('motor_firmas/templates/motor_firmas/trazabilidad.html', 'w') as f:
    f.write(content)
print("Finished patching trazabilidad.html")
