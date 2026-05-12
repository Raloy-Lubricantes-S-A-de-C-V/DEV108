import sys

with open('motor_firmas/templates/motor_firmas/portal_configurar_pdf.html', 'r') as f:
    content = f.read()

# 1. Add pagination controls
old_html = '''    <div class="pdf-area">
        <a href="/portal/mis-pdfs/" style="align-self: flex-start; color: #475569; text-decoration: none; font-weight: bold; margin-bottom: 10px;">⬅ Volver</a>
        <div id="pdf-wrapper">
            <canvas id="pdf-render"></canvas>
            </div>
    </div>'''

new_html = '''    <div class="pdf-area">
        <div style="width: 100%; display: flex; justify-content: space-between; margin-bottom: 15px;">
            <a href="/portal/mis-pdfs/" style="color: #475569; text-decoration: none; font-weight: bold;">⬅ Volver</a>
            <div style="display: flex; gap: 10px; align-items: center; background: white; padding: 5px 15px; border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <button onclick="changePage(-1)" style="border:none; background:none; cursor:pointer; font-weight:bold; color:#3b82f6;">⬅ Anterior</button>
                <span id="pageInfo" style="font-weight: bold; color: #334155;">Página 1 de 1</span>
                <button onclick="changePage(1)" style="border:none; background:none; cursor:pointer; font-weight:bold; color:#3b82f6;">Siguiente ➡</button>
            </div>
        </div>
        <div id="pdf-wrapper">
            <canvas id="pdf-render"></canvas>
        </div>
    </div>'''
content = content.replace(old_html, new_html)

# 2. Update JS rendering and pagination logic
old_js1 = '''        let boxes = [];
        let activeBoxId = null;

        // 1. RENDERIZAR EL PDF
        pdfjsLib.getDocument(url).promise.then(pdfDoc => {
            pdfDoc.getPage(1).then(page => {
                const scale = 1.5;
                const viewport = page.getViewport({ scale: scale });
                const canvas = document.getElementById('pdf-render');
                const ctx = canvas.getContext('2d');
                canvas.height = viewport.height;
                canvas.width = viewport.width;

                wrapper.style.width = viewport.width + 'px';
                wrapper.style.height = viewport.height + 'px';

                page.render({ canvasContext: ctx, viewport: viewport });
            });
        });'''

new_js1 = '''        let boxes = [];
        let activeBoxId = null;
        let pdfDocument = null;
        let currentPage = 1;
        let totalPages = 1;

        // 1. RENDERIZAR EL PDF
        pdfjsLib.getDocument(url).promise.then(pdfDoc => {
            pdfDocument = pdfDoc;
            totalPages = pdfDoc.numPages;
            renderPage(currentPage);
        });

        function renderPage(num) {
            pdfDocument.getPage(num).then(page => {
                const scale = 1.5;
                const viewport = page.getViewport({ scale: scale });
                const canvas = document.getElementById('pdf-render');
                const ctx = canvas.getContext('2d');
                canvas.height = viewport.height;
                canvas.width = viewport.width;

                wrapper.style.width = viewport.width + 'px';
                wrapper.style.height = viewport.height + 'px';

                page.render({ canvasContext: ctx, viewport: viewport });
                document.getElementById('pageInfo').innerText = `Página ${num} de ${totalPages}`;
                
                // Mostrar/Ocultar firmas según la página
                boxes.forEach(b => {
                    const el = document.getElementById(b.id);
                    if(el) {
                        el.style.display = (b.page === num) ? 'flex' : 'none';
                    }
                });
            });
        }
        
        function changePage(delta) {
            let newPage = currentPage + delta;
            if(newPage >= 1 && newPage <= totalPages) {
                currentPage = newPage;
                renderPage(currentPage);
            }
        }'''
content = content.replace(old_js1, new_js1)

# 3. Update box insertion and payload
old_js2 = '''            // Estructura de datos por firma
            const boxData = { id: id, orden: ordenNum, nombre: '', email: '', iniciales: '' };'''

new_js2 = '''            // Estructura de datos por firma (guardando la página actual)
            const boxData = { id: id, orden: ordenNum, nombre: '', email: '', iniciales: '', page: currentPage };'''
content = content.replace(old_js2, new_js2)

old_js3 = '''                payloadFirmantes.push({
                    nombre: b.nombre,
                    email: b.email,
                    iniciales: b.iniciales,
                    orden: parseInt(b.orden),
                    coordenadas: { page: 1, x: xPercent, y: yPercent }
                });'''

new_js3 = '''                payloadFirmantes.push({
                    nombre: b.nombre,
                    email: b.email,
                    iniciales: b.iniciales,
                    orden: parseInt(b.orden),
                    coordenadas: { page: b.page, x: xPercent, y: yPercent }
                });'''
content = content.replace(old_js3, new_js3)

with open('motor_firmas/templates/motor_firmas/portal_configurar_pdf.html', 'w') as f:
    f.write(content)

print("Done")
