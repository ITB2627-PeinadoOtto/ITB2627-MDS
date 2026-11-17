from time import sleep

# region Declaració de Funcions ----------
def recopilar_ingredients():
    print("Comprar al supermercat")
    sleep(1)
    print("Disposar-los sobre el marbre")
    sleep(1)

def cuinar_tallarines():
    print("Cuinar tallarines")
    #sleep(5)
    animacio_cuinar(15)
    print("FI Cuinar tallarines")

def cuinar_pastanagues():
    print("Cuinar pastanagues")
    #sleep(3)
    animacio_cuinar()
    print("FI Cuinar pastanagues")

def animacio_cuinar(temps=3):
    for i in range(temps * 2):
        punts = "." * ((i % 3) + 1)
        print(f"\rCuinant {punts}   ", end="", flush=True)
        sleep(0.5)
    print()

# endregion

# region INICI: Preparar fideus Yakisoba
recopilar_ingredients()
cuinar_tallarines()
cuinar_pastanagues()
# endregion