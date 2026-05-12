import re

text = "{{CONDITION:NUEVO_RENOVACIO\nN_REASIGNACION}}\n{{MAIL_PERSONALIZADO_GENERI\nCO}}"

key = "MAIL_PERSONALIZADO_GENERICO"
flex_key = r"\s*".join(re.escape(char) for char in key)
pattern = r"\{\{" + flex_key + r"(?::.*?)?\}\}"

matches = re.findall(pattern, text, re.DOTALL)
print("Matches:", matches)
