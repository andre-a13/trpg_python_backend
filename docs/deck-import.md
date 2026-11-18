# Importer un deck depuis un tableur

Depuis la page du deck actif, son propriétaire ou un administrateur peut choisir **Importer un deck**, charger un fichier, vérifier les correspondances et ajouter les exemplaires sélectionnés. L'import ajoute au deck existant et conserve les cartes déjà tirées. Aucun remplacement automatique et aucune carte custom inventée.

## Format

CSV UTF-8 (BOM accepté), séparateur virgule, point-virgule ou tabulation ; ou XLSX avec un onglet `Deck` (insensible à la casse), sinon un unique onglet. Les colonnes sont positionnelles, dans cet ordre :

| Colonne | Valeur |
| --- | --- |
| A | Carte (FR), nom obligatoire |
| B | Quantité entière de 1 à 500, 1 si vide |
| C | Type, par exemple Sort, Serviteur, Arme, Héros, Lieu |
| D | Coût entier positif ou nul, facultatif |
| E | Stats ATQ/PV : `3/2` ou `3-2`, facultatif |
| F | Effet (résumé), facultatif, retours à la ligne acceptés |
| G | URL d'illustration HTTP(S), facultative |
| H | Dorée : Oui / Non ; obligatoire pour transmettre une édition dorée en CSV |

Les lignes vides, les en-têtes `Carte (FR)` et le total `Nombre de carte dans le deck` sont ignorés, y compris les en-têtes placés en bas du fichier d'origine. Les adaptations renseignées sont conservées, les champs vides utilisent le catalogue. Les types français connus sont traduits vers les types du catalogue.

En XLSX, le remplissage jaune uni de la cellule A indique une carte dorée (couleur RVB ou jaune de la palette indexée). La colonne H permet également de préciser l'édition. Un fond jaune avec `Dorée=Non` est signalé comme incohérent. Les statistiques que Google Sheets a converties en dates avec un format `d-m` ou `d/m` sont récupérées selon leur affichage ATQ/PV. Les nombres entiers stockés sous la forme `1.0` sont acceptés.

Limites : 2 Mio par fichier, 1 000 lignes, 500 exemplaires par import ; CSV 20 colonnes maximum, XLSX A:Z, seuls A:H sont importés. Les formules des lignes de cartes doivent être remplacées par leurs valeurs avant import. Le lecteur Excel ne charge aucun lien externe et limite la taille décompressée et le nombre d'entrées ZIP.

## Correspondances et cartes custom

Les noms sont comparés sans tenir compte de la casse, des accents et de la ponctuation. Une édition stable hors réimpression CORE/VAN est présélectionnée pour les noms reconnus ; les autres éditions restent choisissables. Les noms approximatifs proposent des candidats et demandent une sélection explicite. Une recherche manuelle permet de choisir une autre carte du catalogue. Les suggestions incluent les formulations anciennes du deck Aleatarius.

Les lignes sans carte sélectionnée ne sont pas envoyées à la validation d'ajout. Elles restent visibles après l'import et peuvent être téléchargées avec **Exporter les cartes en attente**, dans le même format CSV, avec leurs effets, statistiques, quantités et édition. Elles ne sont pas enregistrées comme cartes custom dans la base. Une ligne invalide demande de corriger et recharger le fichier avant validation.

## API et concurrence

- `POST /characters/{slug}/deck/import/preview` (`decksPreviewImport`) : `{filename, contentBase64}`. Renvoie les lignes, données d'origine, candidats, choix initiaux, erreurs et révision courante. Lecture seule.
- `POST /characters/{slug}/deck/import` (`decksCommitImport`) : `{expectedRevision, selections: [{source, sourceCardId}]}`. Valide tous les identifiants et quantités avant mutation, regroupe les définitions identiques et ajoute les exemplaires normaux/dorés dans une transaction.
- Les deux routes vérifient la visibilité du personnage, le droit de gérer le deck et son activation.
- Une modification depuis l'aperçu, deux validations concurrentes ou une répétition de la même validation donnent `409`. Après un résultat réseau incertain, vérifier le deck avant de refaire un aperçu : le même fichier ajouté volontairement depuis un nouvel aperçu constitue un nouvel ajout.
- Les schémas Pydantic font autorité ; contrat OpenAPI et client frontend régénérés par les scripts du dépôt.

## Vérifications

Tests unitaires du parseur, de la validation et des correspondances : `python -m unittest tests.test_deck_import -v`.
Scénario API sur base temporaire : `python -m unittest tests.test_security_data.SecurityDataTests.test_deck_import_preview_append_permissions_atomicity_and_revision -v`.
Les tests frontend couvrent l'aperçu, les choix explicites, l'export des cartes manquantes et les conflits ; `npm run test:integration` couvre le parcours du client généré vers une API HTTP isolée.
