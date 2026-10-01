edat = int(input("Quina edat tens? "))
roba = input("La teva roba és blanca? (si/no) ")
entrada = input("Tens entrada? (si/no) ")
if edat >= 18 and roba == "si" and entrada == "si": 
    print("Pots entrar a la discoteca")
else: 
    print("No pots entrar a la discoteca perquè no compleixes els requisits")