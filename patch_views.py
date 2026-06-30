import re

with open('motor_firmas/views.py', 'r') as f:
    content = f.read()

old_str = """    qrs_firmx = []
    if es_firmx:
        if summary_data.get('qr_local_path'):
            qr_firmx_url = f"{settings.MEDIA_URL}{summary_data['qr_local_path']}"
        
        qrs_raw = summary_data.get('qrs', [])
        if qrs_raw:
            for q in qrs_raw:
                qrs_firmx.append({
                    'email': q.get('email', 'Firmante'),
                    'url': f"{settings.MEDIA_URL}{q['qr_local_path']}" if q.get('qr_local_path') else "",
                    'link': q.get('url_qr_code', '')
                })

    # URLs FIRMX para visualizar documento original y certificado"""

new_str = """    qrs_firmx = []
    qrs_raw = summary_data.get('qrs', [])
    if es_firmx:
        if summary_data.get('qr_local_path'):
            qr_firmx_url = f"{settings.MEDIA_URL}{summary_data['qr_local_path']}"
        
        if qrs_raw:
            for q in qrs_raw:
                qrs_firmx.append({
                    'email': q.get('email', 'Firmante'),
                    'url': f"{settings.MEDIA_URL}{q['qr_local_path']}" if q.get('qr_local_path') else "",
                    'link': q.get('url_qr_code', '')
                })

    for f in firmantes:
        if es_firmx:
            link = ""
            for q in qrs_raw:
                if q.get('email') == f.get('email'):
                    link = q.get('url_qr_code', '')
                    break
            f['whatsapp_link'] = link
        else:
            token_firmante = f.get('token_firmante', '')
            f['whatsapp_link'] = f"{PUBLIC_BASE_URL}/firmar/{proceso.token_acceso}/{token_firmante}/"

    # URLs FIRMX para visualizar documento original y certificado"""

if old_str in content:
    content = content.replace(old_str, new_str)
    with open('motor_firmas/views.py', 'w') as f:
        f.write(content)
    print("Success replacing views.py")
else:
    print("Failed to find old string in views.py")
