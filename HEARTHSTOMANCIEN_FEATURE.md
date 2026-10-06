# Feature Hearthstomancien

## Objectif

Fournir à chaque personnage autorisé un deck persistant de cartes Hearthstone françaises, configurable par son propriétaire ou un administrateur, visible en lecture seule par ses coéquipiers et activable uniquement par un administrateur.

## Règles métier validées

- Le catalogue provient du snapshot français `cards.json` et expose uniquement les cartes `collectible: true`.
- Une carte ajoutée au deck devient une définition locale éditable : nom, coût, attaque, PV, durabilité, effet, type, rareté, classe, tribu, école, extension et illustration.
- Une définition qui diffère de sa carte Hearthstone source sur au moins un champ éditable est une variante et s'affiche avec son portrait brut sans décoration officielle ; une définition inchangée conserve le rendu complet Hearthstone.
- Des définitions strictement identiques sont fusionnées. Les exemplaires normaux et dorés restent comptés et affichés séparément.
- Le deck est sans limite de taille, de classe, de rareté ou de nombre de copies.
- Piocher sort une seule copie du paquet. L'ordre restant n'est jamais exposé.
- Défausser une carte tirée la remet dans le paquet et remélange celui-ci.
- Jouer une carte normale la détruit. Une carte dorée ne peut pas être jouée/détruite.
- Le dernier jeu peut être annulé jusqu'à la mutation suivante ; l'exemplaire revient alors dans les cartes tirées.
- Une carte normale ou dorée peut être supprimée volontairement directement depuis le paquet, une copie à la fois et sans modale de confirmation. Une carte tirée doit d'abord être défaussée pour revenir dans le paquet. Cette suppression est définitive, sans motif ni historique et sans annulation.
- Reset remet les cartes tirées dans le paquet et mélange, sans restaurer les cartes jouées ou supprimées.
- La sauvegarde de composition réinitialise et mélange le paquet.
- L'ouverture d'un paquet choisit cinq cartes collectionnables distinctes dans l'extension sélectionnée, avec au moins une carte rare ou supérieure. Les raretés cibles sont 69,25 % commune, 24 % rare, 5,25 % épique et 1,50 % légendaire ; les cartes `FREE` des sets techniques sont assimilées aux communes. Les cartes restent visibles après leur révélation puis les cinq copies normales sont ajoutées ensemble au deck lors de l'enregistrement, sans déplacer les cartes déjà tirées.
- Un deck désactivé reste visible en lecture seule et conserve son état.
- Admin : activation, composition et jeu. Propriétaire : composition et jeu si actif. Coéquipier visible : lecture seule.
- L'interface est bilingue FR/EN ; le contenu des cartes reste en français.

## Architecture retenue

- `CharacterDeck` : configuration, activation, révision transactionnelle et action annulable.
- `DeckCardDefinition` : données matérialisées et éditables de la carte.
- `DeckCardCopy` : exemplaire physique, statut doré, zone et clé de mélange.
- Catalogue JSON versionné dans le backend, chargé en mémoire et paginé par l'API ; ses 40 codes de set sont rattachés à des noms d'extension français et peuvent filtrer la recherche.
- Module Deck sur la fiche et page dédiée `/characters/:slug/deck`.
- Constructeur partagé entre les vues complète et minimaliste, présenté dans une modale desktop ouverte par « Ajouter une carte ».
- La Presse Hearthstone actuelle reste inchangée ; le modèle local pourra recevoir ses cartes ultérieurement.

## Contrats API prévus

- `PATCH /characters/{slug}/hearthstomancer`
- `GET /hearthstone/cards?q={nom}&cardSet={code}&page={n}&pageSize={n}` ; la réponse inclut `sets` (`code`, `name`, `cardCount`) pour construire le filtre.
- `GET /characters/{slug}/deck`
- `PUT /characters/{slug}/deck/composition`
- `POST /characters/{slug}/deck/draw`
- `POST /characters/{slug}/deck/copies/{copyId}/discard`
- `POST /characters/{slug}/deck/copies/{copyId}/play`
- `POST /characters/{slug}/deck/remove`
- `POST /characters/{slug}/deck/undo-play`
- `POST /characters/{slug}/deck/reset`
- `POST /characters/{slug}/deck/pack/open` — tire cinq définitions distinctes dans un set sans modifier le deck.
- `POST /characters/{slug}/deck/pack/save` — ajoute atomiquement les cinq copies normales révélées sans réinitialiser les cartes tirées.

## Checklist

- [x] Snapshot du catalogue intégré et service de recherche ajouté
- [x] Tous les sets du snapshot nommés et filtrables dans le catalogue
- [x] Migration et modèles de deck ajoutés
- [x] API, permissions et règles de jeu ajoutées
- [x] Tests backend ajoutés et validés
- [x] Types et services frontend ajoutés
- [x] Contrôle admin d'activation ajouté
- [x] Module de fiche ajouté
- [x] Page de deck et constructeur ajoutés
- [x] Traductions FR/EN ajoutées
- [x] Lint et build frontend validés

## Journal des itérations

### Itération 0 — Initialisation du suivi

- Statut : Terminée
- Objectif : consigner la spécification validée avant toute modification de code.
- Changements : création de ce journal, transcription des règles métier, de l'architecture et des contrats prévus.
- Vérifications : fichier relu depuis le dépôt backend ; règles, architecture, API et checklist présentes.

### Itération 1 — Catalogue, schéma et API backend

- Statut : Terminée
- Objectif : intégrer le snapshot, créer la persistance et implémenter les contrats backend avec leurs permissions.
- Changements : snapshot FR copié ; service de catalogue collectionnable avec recherche/pagination ; migration 013 ; modèles deck/définitions/copies ; sérialisation du statut sur les personnages ; routes d'activation, composition, pioche, défausse, jeu, annulation, suppression et reset ; tests de cycle de vie et de lecture d'équipe.
- Vérifications : analyse syntaxique des 20 fichiers Python ; suite complète `python -m unittest` réussie (22 tests) ; tests Hearthstomancien ciblés réussis (2 tests), sans avertissement de double suppression après correction.

### Itération 2 — Contrats et contrôle admin frontend

- Statut : Terminée
- Objectif : ajouter les types/services du deck et le contrôle d'activation au dashboard administrateur.
- Changements : DTOs de catalogue/deck ; service API complet ; statut Hearthstomancien dans le modèle Character ; interrupteur tri-état dans le dashboard avec retours traduits.
- Vérifications : `npm run build` et `npm run lint` réussis.

### Itération 3 — Module de fiche et page de deck

- Statut : Terminée
- Objectif : livrer l'expérience de jeu, la consultation et le constructeur de deck bilingue.
- Changements : composant de carte avec rendu officiel/illustration personnalisée et valeurs locales ; habillage doré ; modale de suppression ; module de fiche ; nouvelle page de deck ; constructeur avec recherche, variantes, édition complète et brouillon ; route dédiée ; traductions FR/EN ; positionnement du nouveau module dans la fiche.
- Vérifications : `npm run build` et `npm run lint` réussis ; test backend de pioches concurrentes réussi, sans duplication d'exemplaire.

### Itération 4 — Vérification intégrée et finitions

- Statut : Terminée
- Objectif : vérifier l'intégration complète, corriger les défauts observés et produire le bilan final.
- Changements : correction du conflit entre le layout global `.page` et la page de deck ; ajout d'une grille locale prioritaire et ajustements des contrôles du constructeur sur petit écran ; préparation d'une base de démonstration isolée avec un personnage, un deck normal/doré et une variante personnalisée.
- Vérifications : suite backend complète réussie (23 tests), y compris permissions, concurrence, suppression et annulation ; `npm run lint` et `npm run build` réussis ; parcours visuel du dashboard, de la page de deck et du module de fiche ; contrôle responsive à 438 px et 1280 px sans débordement ; aucune erreur ni aucun avertissement dans la console navigateur.

## Écarts et décisions d'implémentation

- La suppression d'une copie persistante depuis le constructeur ne passe pas par une diminution de quantité dans le brouillon : elle utilise toujours l'action dédiée afin de supprimer directement un seul exemplaire.
- Les doublons de nom du catalogue sont conservés lorsque leurs identifiants Hearthstone diffèrent ; ils représentent des impressions officielles distinctes pouvant servir de base à une définition locale.
- Les avertissements Python de dépréciation sur `datetime.utcnow()` proviennent majoritairement de l'infrastructure existante et n'empêchent pas la suite de tests de réussir.

### Itération 5 — Vue compacte, sauvegarde locale et micro-interactions

- Statut : Terminée
- Objectif : ajouter une vue minimaliste centrée sur la liste des cartes avec détails au survol, corriger l'échec CORS observé lors de la sauvegarde locale et renforcer le feedback visuel des interactions.
- Changements : autorisation de la méthode `PUT` dans le middleware CORS ; test de prérequête dédié ; sélecteur persistant Vue complète/Vue minimaliste ; liste compacte avec coût, nom et quantités toujours visibles puis statistiques, effet, métadonnées et suppressions révélés au survol ou au focus ; retours de succès temporaires et indicateur d'activité ; transitions légères sur boutons, cartes, catalogue et éditeur, avec respect de `prefers-reduced-motion` ; traductions FR/EN.
- Vérifications : test CORS ciblé réussi ; sauvegarde réelle depuis `http://127.0.0.1:5173` validée avec `OPTIONS 200` puis `PUT 200` et message de succès ; vue minimaliste contrôlée à 438 px sans débordement, détails révélés au focus et console navigateur sans erreur ; suite backend complète réussie (24 tests) ; `npm run lint` et `npm run build` réussis.

### Itération 6 — Listing desktop illustré et séparation normale/dorée

- Statut : Terminée
- Objectif : transformer la vue minimaliste desktop en listing trié par coût avec infobulle illustrée au survol, conserver le comportement dépliable sur mobile et séparer visuellement les exemplaires normaux des exemplaires dorés.
- Changements : génération de deux listes distinctes normales/dorées à partir des définitions ; tri par coût puis par nom ; infobulle desktop avec rendu ou illustration personnalisée, statistiques, effet, métadonnées et action disponible ; conservation du détail déplié dans le flux sur mobile ; séparation normale/dorée également appliquée aux cartes tirées et à la composition complète ; encadrement, badge et accent dorés conservés au repos, au survol et au focus.
- Vérifications : rendu desktop contrôlé à 1280 px avec infobulle absolue de 440 px et illustration visible ; ordre par coût vérifié ; variante dorée contrôlée avec cadre doré et infobulle dédiée ; rendu mobile contrôlé à 438 px avec détail dans le flux, illustration de l'infobulle masquée et aucun débordement ; vue complète contrôlée avec groupes normaux/dorés distincts ; console navigateur sans erreur ; `npm run lint` et `npm run build` réussis.

### Itération 7 — Extensions filtrables et composition en modale

- Statut : Terminée
- Objectif : inventorier tous les sets du snapshot et les rattacher à des extensions lisibles, ajouter le filtre d'extension au catalogue, puis unifier la composition complète et minimaliste autour d'une modale ouverte par « Ajouter une carte ».
- Changements : inventaire exhaustif des 40 groupes du snapshot (5 845 cartes collectionnables), y compris les groupes techniques et sans code ; table de correspondance vers les noms français des extensions ; ajout de `cardSetName` aux cartes, de la collection `sets` aux pages de catalogue et du paramètre de filtre exact `cardSet` ; sélecteur d'extension avec volumes et total de résultats ; déplacement de l'éditeur de définitions et du catalogue dans une modale desktop ; bouton « Ajouter une carte » commun aux vues complète et minimaliste ; fermeture protégée lorsqu'un brouillon est modifié ; traductions et styles associés.
- Vérifications : suite backend complète réussie (24 tests), avec assertions sur les 40 groupes, les 5 845 cartes, le libellé et le filtrage de `TGT`, ainsi que le groupe sans code ; `npm run lint` et `npm run build` réussis. Conformément à la demande de l'utilisateur, aucun test UI ni aucune ouverture de navigateur n'a été effectué.

### Itération 8 — Sélection unitaire et cohérence des cartes tirées

- Statut : Terminée
- Objectif : simplifier la modale pour n'éditer que la dernière carte sélectionnée avant son ajout, retirer la confirmation de sauvegarde, exclure les cartes tirées du listing du paquet et présenter ces cartes tirées avec le même listing compact en vue minimaliste.
- Changements : suppression du listing complet des définitions dans la modale ; sélection unitaire depuis le catalogue avec éditeur des valeurs de la dernière carte choisie, puis ajout explicite d'une copie normale ou dorée au brouillon ; conservation interne et sauvegarde groupée du brouillon ; suppression de la confirmation avant Enregistrer ; largeur complète des sections en vue minimaliste ; libellés de suppression unifiés en « Supprimer » ; alignement des actions au bas des cartes complètes ; calcul des listings à partir des seuls exemplaires encore dans le paquet ; nouveau listing compact des cartes tirées en tête de la vue minimaliste avec Défausser, Jouer et Supprimer.
- Vérifications : `npm run lint` et `npm run build` réussis ; le build conserve uniquement l'avertissement non bloquant existant sur la taille du bundle principal. Aucun test UI par navigateur n'a été effectué.

### Itération 9 — Pioche en vue minimaliste

- Statut : Terminée
- Objectif : rendre l'action de pioche directement accessible depuis la vue minimaliste.
- Changements : ajout du bouton « Tirer une carte » dans l'en-tête des cartes tirées en vue minimaliste ; reprise des mêmes permissions, blocages pendant une mutation ou un brouillon et désactivation lorsque le paquet est vide ; réutilisation du feedback de pioche existant.
- Vérifications : `npm run lint` et `npm run build` réussis ; seul l'avertissement non bloquant déjà connu sur la taille du bundle principal subsiste. Aucun test UI par navigateur n'a été effectué.

### Itération 10 — Suppression limitée au paquet

- Statut : Terminée
- Objectif : retirer l'action Supprimer des cartes tirées et réserver la suppression volontaire aux exemplaires encore présents dans le paquet, interface et API comprises.
- Changements : retrait du bouton Supprimer sur les cartes tirées dans les vues complète et minimaliste ainsi que dans le module de la fiche personnage ; simplification des contrats frontend de suppression ; restriction du payload backend à `zone: "deck"` ; une carte tirée doit désormais être défaussée avant de pouvoir être supprimée depuis le paquet ; règles métier du présent document mises à jour.
- Vérifications : suite backend complète réussie (24 tests), dont rejet explicite d'une suppression en zone `drawn` et suppression normale/dorée depuis le paquet ; `npm run lint` et `npm run build` réussis. Aucun test UI par navigateur n'a été effectué.

### Itération 11 — Actions rapides du listing minimaliste

- Statut : Terminée
- Objectif : exposer directement les actions Jouer et Défausser sur chaque carte tirée du listing minimaliste avec des boutons à icône.
- Changements : ajout, à droite de chaque carte tirée, d'un bouton circulaire Jouer avec icône de lecture et d'un bouton Défausser avec icône de mélange ; libellés accessibles et infobulles natives conservés pour les boutons à icône ; l'action Jouer reste absente des cartes dorées conformément aux règles métier.
- Vérifications : `npm run lint` et `npm run build` réussis ; seul l'avertissement non bloquant connu sur la taille du bundle principal subsiste. Aucun test UI par navigateur n'a été effectué.

### Itération 12 — Ouverture animée d'un paquet

- Statut : Terminée
- Objectif : ajouter, à côté de « Ajouter une carte », un parcours de sélection d'extension puis d'ouverture de cinq cartes face cachée, chaque révélation ajoutant immédiatement la carte au deck sans perturber les cartes déjà tirées.
- Changements : ajout du bouton « Ouvrir un paquet » à côté de « Ajouter une carte » ; modale sombre avec sélection parmi les 40 sets et confirmation ; tirage backend sécurisé de cinq cartes collectionnables distinctes ; distribution uniforme avec dos classique Hearthstone, animation d'arrivée et retournement 3D individuel ; ajout transactionnel d'une copie normale à chaque révélation, fusion avec une définition identique, mélange de la nouvelle copie et conservation des cartes déjà tirées ; état d'ajout, progression, gestion des erreurs et traductions FR/EN. L'ouverture en cours reste volontairement éphémère côté interface et aucun historique de paquet n'est conservé.
- Vérifications : suite backend complète réussie (24 tests), avec contrôle de cinq cartes distinctes du set demandé et ajout d'une copie ; `npm run lint` et `npm run build` réussis ; URL du dos classique vérifiée avec une réponse HTTP 200. Aucun test UI par navigateur n'a été effectué.

### Itération 13 — Suppression directe et sauvegarde groupée du paquet

- Statut : Terminée
- Objectif : supprimer la modale de confirmation des suppressions et différer l'ajout des cinq cartes retournées jusqu'au clic sur « Enregistrer ».
- Changements : suppression du composant et de l'état de confirmation ; les actions Supprimer des listes complète et minimaliste appellent désormais directement l'API pour retirer un seul exemplaire ; les cinq cartes d'un paquet restent face visible après leur retournement sans modifier le deck ; remplacement du bouton Fermer par Enregistrer, activé après les cinq révélations ; nouvel endpoint transactionnel `pack/save` qui valide cinq identifiants distincts, fusionne les définitions identiques et ajoute les cinq copies normales en une seule révision ; textes FR/EN et styles devenus obsolètes nettoyés.
- Vérifications : suite backend complète réussie (24 tests), dont ouverture puis sauvegarde groupée des cinq cartes ; `npm run lint` et `npm run build` réussis. Le build conserve uniquement l'avertissement non bloquant connu sur la taille du bundle principal. Conformément à la demande de l'utilisateur, aucun test UI par navigateur n'a été effectué.

### Itération 14 — Portrait brut des variantes

- Statut : Terminée
- Objectif : afficher uniquement l'illustration brute d'une carte lorsqu'elle constitue une variante locale de sa définition Hearthstone d'origine.
- Changements : ajout du marqueur API `isVariant`, calculé en comparant l'empreinte de tous les champs éditables de la définition persistée à celle de la carte du snapshot ; les variantes dont le nom, les statistiques, l'effet, les métadonnées ou l'illustration diffèrent utilisent désormais `illustrationUrl` dans les cartes complètes, compactes, tirées et les infobulles minimalistes ; les cartes officielles inchangées continuent d'utiliser `renderUrl`.
- Vérifications : suite backend complète réussie (24 tests), avec assertions explicites sur une carte de paquet non variante et une définition personnalisée variante ; `npm run lint` et `npm run build` réussis. Le build conserve uniquement l'avertissement non bloquant connu sur la taille du bundle principal. Aucun test UI par navigateur n'a été effectué.

### Itération 15 — Déploiement en production

- Statut : Terminée
- Objectif : déployer en production les itérations Hearthstomancien validées, puis vérifier la disponibilité des services et des nouveaux contrats API.
- Changements : publication du backend Hearthstomancien sur le commit de production `f388c51`, puis de la pondération des paquets sur `40d7f52` ; publication du frontend combinant la Forge existante et le deck sur `9c4848c` ; reconstruction et recréation des deux conteneurs Docker ; conservation de la base active et création, avant chaque déploiement backend, d'une sauvegarde locale et d'un snapshot S3. Dernières sauvegardes : `data/backups/data-20261006T182818Z.db` et `save/data-20261006T182820Z.db`.
- Vérifications : images Docker construites avec succès ; conteneurs `trpg-api` et `trpg-frontend-app` sains ; `https://api.arnaud-a.dev/health` répond `{"ok":true}` ; `https://game.arnaud-a.dev/characters/hearth-qa/deck` répond HTTP 200 ; contrôle automatisé dans le conteneur backend de 50 paquets conformes. Aucun test UI par navigateur n'a été effectué.

### Itération 16 — Pondération des raretés à l'ouverture d'un paquet

- Statut : Terminée
- Objectif : rapprocher le tirage de cinq cartes des taux publiés pour les paquets Hearthstone, tout en accordant un léger bonus aux cartes épiques et légendaires.
- Changements : taux Hearthstone de référence consignés (commune 71,65 %, rare 22,84 %, épique 4,42 %, légendaire 1,10 %) ; taux cibles retenus : commune 69,25 %, rare 24 %, épique 5,25 % et légendaire 1,50 % ; ajout d'un emplacement rare ou supérieur garanti puis de quatre emplacements calibrés afin de préserver les taux cibles finaux ; tirage sans remise et ordre final remélangé ; assimilation de la rareté technique `FREE` à commune. Sources consultées : boutique Battle.net, annonce Blizzard sur les paquets de rattrapage et statistiques Hearthstone Wiki issues des taux publiés.
- Vérifications : test ciblé réussi ; calibration mathématique des quatre taux, garantie rare ou supérieure et unicité des cinq identifiants vérifiées ; simulation déterministe de 20 000 paquets : commune 69,192 %, rare 24,019 %, épique 5,256 %, légendaire 1,533 % ; suite backend complète réussie (25 tests) ; contrôle de 50 paquets dans le conteneur de production réussi après déploiement.

