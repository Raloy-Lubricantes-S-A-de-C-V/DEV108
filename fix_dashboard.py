import sys
import re

with open('motor_firmas/templates/motor_firmas/admin_dashboard.html', 'r') as f:
    content = f.read()

# I see in the previous output:
#         <div class="card">
#             <h3>Agregar Nuevo Administrador</h3>
#             <p style="font-size: 0.85rem; color:#666;">Cualquier usuario invitado podrá usar su mismo PIN para entrar a este portal.</p>
#             <input type="email" id="addAdminMail" class="side-input" placeholder="nuevo.admin@raloy.com.mx">
#             <button class="side-btn" onclick="ejecutarAccion('agregar_admin', {email: document.getElementById('addAdminMail').value})" style="background: #27ae60;">Otorgar Privilegios</button>

block_to_remove = r'''        <div class="card">
            <h3>Agregar Nuevo Administrador</h3>
            <p style="font-size: 0.85rem; color:#666;">Cualquier usuario invitado podrá usar su mismo PIN para entrar a este portal\.</p>
            <input type="email" id="addAdminMail" class="side-input" placeholder="nuevo\.admin@raloy\.com\.mx">
            <button class="side-btn" onclick="ejecutarAccion\('agregar_admin', \{email: document\.getElementById\('addAdminMail'\)\.value\}\)" style="background: #27ae60;">Otorgar Privilegios</button>
        </div>'''

content = re.sub(block_to_remove, '', content, flags=re.DOTALL)

with open('motor_firmas/templates/motor_firmas/admin_dashboard.html', 'w') as f:
    f.write(content)

