import random
import requests

API_KEY = "v56pVZuvAhXJaSSeCRcu7SMvpqyc9Ldk6qT5bmNF"
URL = "https://api.api-ninjas.com/v1/animals"

# Catálogo organizado: ("Nombre en español", "nombre_exacto_en_ingles")
CATALOGO = {
    "Mamíferos terrestres": [
        ("León", "lion"),
        ("Tigre", "tiger"),
        ("Guepardo", "cheetah"),
        ("Lobo", "wolf"),
        ("Oso polar", "polar bear"),
        ("Elefante", "elephant"),
        ("Gorila", "gorilla"),
        ("Canguro", "kangaroo"),
        ("Zorro rojo", "red fox"),
        ("Panda gigante", "giant panda"),
    ],
    "Animales marinos": [
        ("Tiburón blanco", "great white shark"),
        ("Orca", "killer whale"),
        ("Delfín", "dolphin"),
        ("Pulpo", "octopus"),
        ("Ballena azul", "blue whale"),
        ("Tortuga marina", "sea turtle"),
        ("Medusa", "jellyfish"),
        ("Caballito de mar", "seahorse"),
    ],
    "Aves": [
        ("Águila calva", "bald eagle"),
        ("Halcón peregrino", "peregrine falcon"),
        ("Pingüino emperador", "emperor penguin"),
        ("Búho", "owl"),
        ("Flamenco", "flamingo"),
        ("Colibrí", "hummingbird"),
        ("Avestruz", "ostrich"),
    ],
    "Reptiles y anfibios": [
        ("Dragón de Komodo", "komodo dragon"),
        ("Cocodrilo", "crocodile"),
        ("Cobra real", "king cobra"),
        ("Camaleón", "chameleon"),
        ("Rana dardo venenosa", "poison dart frog"),
        ("Iguana", "iguana"),
        ("Ajolote", "axolotl"),
    ],
}


def consultar_api(nombre_ingles):
    headers = {"X-Api-Key": API_KEY}
    params = {"name": nombre_ingles}

    try:
        respuesta = requests.get(URL, headers=headers, params=params, timeout=10)
        respuesta.raise_for_status()
        return respuesta.json()
    except requests.exceptions.HTTPError as err:
        print(f"Error en la petición HTTP: {err}")
    except requests.exceptions.RequestException as err:
        print(f"Error de conexión: {err}")
    return []


def mostrar_ficha(animal):
    taxonomia = animal.get("taxonomy", {})
    caract = animal.get("characteristics", {})
    ubicaciones = ", ".join(animal.get("locations", ["Desconocida"]))

    print("\n" + "=" * 55)
    print(f"🐾 ANIMAL: {animal.get('name', 'Desconocido').upper()}")
    print(f"🔬 Nombre científico: {taxonomia.get('scientific_name', 'N/A')}")
    print(f"🌍 Ubicación: {ubicaciones}")
    print("-" * 55)
    print(f"• Dieta: {caract.get('diet', 'N/A')}")
    print(f"• Hábitat: {caract.get('habitat', 'N/A')}")
    print(f"• Esperanza de vida: {caract.get('lifespan', 'N/A')}")
    print(f"• Peso: {caract.get('weight', 'N/A')}")
    print(f"• Longitud / Altura: {caract.get('length') or caract.get('height', 'N/A')}")
    print(f"• Velocidad máxima: {caract.get('top_speed', 'N/A')}")
    print(f"• Tipo de piel: {caract.get('skin_type', 'N/A')}")
    print(f"• Dato destacado: {caract.get('slogan', 'N/A')}")
    print("=" * 55 + "\n")


def procesar_busqueda(consulta_ingles):
    resultados = consultar_api(consulta_ingles)

    if not resultados:
        print(f"No se encontraron datos para '{consulta_ingles}'.\n")
        return

    # 1. Priorizar coincidencia exacta
    for animal in resultados:
        if animal.get("name", "").strip().lower() == consulta_ingles.lower():
            mostrar_ficha(animal)
            return

    # 2. Si solo hay un resultado, mostrarlo directamente
    if len(resultados) == 1:
        mostrar_ficha(resultados[0])
        return

    # 3. Si hay múltiples coincidencias parciales, desplegar lista para elegir
    print(f"\nEncontré {len(resultados)} especies relacionadas con '{consulta_ingles}':")
    for i, animal in enumerate(resultados, start=1):
        print(f"  {i}. {animal.get('name', 'Desconocido')}")
    print("  0. Ver todas")

    while True:
        eleccion = input("\nElige un número (o Enter para volver): ").strip()
        if not eleccion:
            print()
            return
        if eleccion.isdigit():
            idx = int(eleccion)
            if idx == 0:
                for animal in resultados:
                    mostrar_ficha(animal)
                return
            if 1 <= idx <= len(resultados):
                mostrar_ficha(resultados[idx - 1])
                return
        print("Opción no válida. Introduce un número de la lista.")


def explorar_catalogo():
    categorias = list(CATALOGO.keys())

    while True:
        print("\n--- CATEGORÍAS DE ANIMALES ---")
        for i, cat in enumerate(categorias, start=1):
            print(f"  {i}. {cat} ({len(CATALOGO[cat])} especies)")
        print("  0. Volver al menú principal")

        opcion_cat = input("\nElige una categoría: ").strip()
        if opcion_cat == "0":
            print()
            return

        if not opcion_cat.isdigit() or not (1 <= int(opcion_cat) <= len(categorias)):
            print("Categoría no válida.")
            continue

        cat_elegida = categorias[int(opcion_cat) - 1]
        lista_animales = CATALOGO[cat_elegida]

        while True:
            print(f"\n--- {cat_elegida.upper()} ---")
            for i, (nombre_es, _) in enumerate(lista_animales, start=1):
                print(f"  {i}. {nombre_es}")
            print("  0. Volver a categorías")

            opcion_ani = input("\nElige un animal para ver su ficha: ").strip()
            if opcion_ani == "0":
                break

            if opcion_ani.isdigit() and 1 <= int(opcion_ani) <= len(lista_animales):
                nombre_es, nombre_en = lista_animales[int(opcion_ani) - 1]
                print(f"\nConsultando ficha de {nombre_es}...")
                procesar_busqueda(nombre_en)
            else:
                print("Número no válido.")


def animal_aleatorio():
    todos = [animal for lista in CATALOGO.values() for animal in lista]
    nombre_es, nombre_en = random.choice(todos)
    print(f"\n🎲 Animal aleatorio seleccionado: {nombre_es}")
    procesar_busqueda(nombre_en)


def main():
    while True:
        print("==========================================")
        print("   ENCICLOPEDIA DE ANIMALES (API NINJAS)  ")
        print("==========================================")
        print("  1. Ver lista de animales por categoría")
        print("  2. Mostrar un animal aleatorio")
        print("  3. Buscar cualquier animal (en inglés)")
        print("  0. Salir")

        opcion = input("\nSelecciona una opción: ").strip()

        if opcion == "1":
            explorar_catalogo()
        elif opcion == "2":
            animal_aleatorio()
        elif opcion == "3":
            busqueda = input("\nEscribe el nombre del animal en inglés: ").strip()
            if busqueda:
                procesar_busqueda(busqueda)
        elif opcion == "0":
            print("¡Hasta luego!")
            break
        else:
            print("Opción no válida. Elige entre 0 y 3.\n")


if __name__ == "__main__":
    main()