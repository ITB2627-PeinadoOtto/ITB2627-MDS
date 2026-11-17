# Programa que demana l'edat i diu si ets major d'edat.
edat = int(input("Quina edat tens? "))

if edat >= 18:
    print("Ets major d'edat")
else:
    print("Ets menor d'edat")

if edat < 18:
    print(f"Et falten {18 - edat} anys per ser major d'edat")

anys_vida = 85 - edat
if edat >= 18:
    print(f"Et falten {anys_vida} anys per a morir (basant-nos en l'esperança de vida mitjana a Espanya, ànims!)")

print("Programa Finalitzat")