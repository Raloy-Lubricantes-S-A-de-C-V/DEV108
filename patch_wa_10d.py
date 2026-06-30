with open('motor_firmas/templates/motor_firmas/trazabilidad.html', 'r') as f:
    content = f.read()

old_html = """            <div class="bg-secondary-container text-on-secondary-container p-3 rounded-lg text-xs font-bold border border-secondary/20 mb-2 flex gap-2">
                <span class="material-symbols-outlined text-[16px]">info</span>
                <p>No tenemos guardado el número telefónico, por lo que es indispensable que coloques el correcto para que le llegue el recordatorio.</p>
            </div>
            <div>
                <label class="block text-sm font-bold text-text-main mb-1">Teléfono (con código de país, ej: 521234567890)</label>
                <input type="text" id="waPhone" class="w-full px-3 py-2 border border-outline-variant rounded-lg focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all font-mono" placeholder="52...">
            </div>"""

new_html = """            <div class="bg-[#FFC107] text-black p-3 rounded-lg text-xs font-medium shadow-sm mb-4 flex gap-2">
                <span class="material-symbols-outlined text-[16px]">info</span>
                <p>No tenemos guardado el número telefónico, por lo que es indispensable que coloques el correcto para que le llegue el recordatorio.</p>
            </div>
            <div>
                <label class="block text-sm font-bold text-text-main mb-1">Teléfono a 10 dígitos (ej: 7228872008)</label>
                <input type="text" id="waPhone" maxlength="10" class="w-full px-3 py-2 border border-outline-variant rounded-lg focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all font-mono" placeholder="7228872008" oninput="this.value = this.value.replace(/[^0-9]/g, '')">
            </div>"""

old_js = """    async function sendWhatsapp() {
        const phone = document.getElementById('waPhone').value.trim();
        if (!phone) {
            alert('Por favor ingresa un número de teléfono.');
            return;
        }

        if (!confirm('¿Confirmas que el número ' + phone + ' es correcto? No lo tenemos guardado, por lo que es indispensable que sea el correcto para que le llegue el recordatorio.')) {
            return;
        }"""

new_js = """    async function sendWhatsapp() {
        const phone = document.getElementById('waPhone').value.trim();
        if (!/^\d{10}$/.test(phone)) {
            alert('Por favor ingresa un número de teléfono válido de exactamente 10 dígitos.');
            return;
        }

        if (!confirm('¿Confirmas que el número ' + phone + ' es correcto? No lo tenemos guardado, por lo que es indispensable que sea el correcto para que le llegue el recordatorio.')) {
            return;
        }"""

if old_html in content:
    content = content.replace(old_html, new_html)
    print("Replaced HTML")
else:
    print("Could not find HTML block")

if old_js in content:
    content = content.replace(old_js, new_js)
    print("Replaced JS")
else:
    print("Could not find JS block")

with open('motor_firmas/templates/motor_firmas/trazabilidad.html', 'w') as f:
    f.write(content)
print("Finished patching trazabilidad.html")
