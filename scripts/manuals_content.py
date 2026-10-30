"""Fictional technical manuals (original content written for the demo, not copied from any manufacturer).

Numerical values are presented as indicative values of a fictional manufacturer or internal procedure.
"""

from __future__ import annotations

MANUALS = [
    {
        "file": "manuel_cta_ax400.pdf",
        "title": "Manuel de maintenance - Centrales de traitement d'air série AX-400 (fictif)",
        "pages": [
            """
<h1>Manuel de maintenance<br/>Centrales de traitement d'air - série AX-400</h1>
<p class="note">Document fictif rédigé pour une démonstration. Fabricant et références imaginaires.</p>
<h2>1. Domaine d'application</h2>
<p>Ce manuel décrit la maintenance préventive et le diagnostic des centrales de traitement d'air (CTA) de la série
AX-400 installées en toiture ou en local technique. Il s'adresse à des techniciens CVC qualifiés.</p>
<h2>2. Consignes de sécurité</h2>
<ul>
<li>Toute intervention sur le moto-ventilateur impose l'arrêt de la CTA et la consignation électrique de l'équipement.</li>
<li>Attendre l'arrêt complet de la turbine avant d'ouvrir les portes d'accès : la roue peut continuer à tourner plusieurs minutes.</li>
<li>Port des équipements de protection individuelle : gants, lunettes, protections auditives.</li>
<li>Les opérations électriques sont réservées au personnel titulaire de l'habilitation électrique adaptée.</li>
</ul>
<h2>3. Maintenance préventive</h2>
<table>
<tr><th>Élément</th><th>Opération</th><th>Périodicité indicative</th></tr>
<tr><td>Filtres F7</td><td>Contrôle de la perte de charge</td><td>Mensuelle</td></tr>
<tr><td>Filtres F7</td><td>Remplacement</td><td>Tous les 6 mois ou si la perte de charge dépasse 250 Pa</td></tr>
<tr><td>Courroies</td><td>Contrôle de la tension et de l'usure</td><td>Trimestrielle</td></tr>
<tr><td>Roulements du moteur</td><td>Graissage et contrôle du bruit</td><td>Annuelle</td></tr>
<tr><td>Batteries chaude et froide</td><td>Nettoyage</td><td>Annuelle</td></tr>
<tr><td>Bac à condensats</td><td>Contrôle de l'écoulement et nettoyage</td><td>Trimestrielle</td></tr>
</table>
<p>Chaque opération doit être tracée dans le carnet de maintenance de l'équipement.</p>
""",
            """
<h2>4. Diagnostic des vibrations anormales</h2>
<p>Une vibration anormale se manifeste par un bruit sourd transmis à la structure, une élévation de la mesure
vibratoire au palier ou des plaintes d'occupants. Elle ne doit pas être ignorée : une vibration persistante
accélère l'usure des roulements et peut conduire à la casse du moto-ventilateur.</p>
<h3>4.1 Causes possibles</h3>
<ul>
<li>Déséquilibre de la turbine, souvent dû à un encrassement des aubes.</li>
<li>Usure des roulements du moteur ou du palier de la turbine.</li>
<li>Courroie détendue, usée ou mal alignée ; mauvais alignement des poulies.</li>
<li>Plots antivibratiles dégradés ou fixations desserrées.</li>
<li>Fonctionnement à une vitesse proche d'une fréquence de résonance de la structure.</li>
</ul>
<h3>4.2 Démarche de diagnostic</h3>
<p>Mesurer la vitesse vibratoire sur les paliers. Valeurs indicatives du fabricant : seuil d'alerte à 4,5 mm/s,
seuil d'arrêt à 7,1 mm/s. Contrôler ensuite la tension et l'alignement de la courroie, l'état des plots
antivibratiles et le serrage des fixations, puis la propreté de la turbine.</p>
<h3>4.3 Recommandations</h3>
<p>Si les vibrations persistent après réglage de la courroie et de l'alignement, le fabricant recommande de
remplacer les roulements et de procéder à un équilibrage dynamique de la turbine. En cas de vibrations
répétées, par exemple trois occurrences sur une période de 30 jours, une analyse vibratoire spectrale doit être
réalisée par un prestataire spécialisé afin d'identifier la cause racine. Au-delà du seuil d'arrêt, la CTA doit
être arrêtée jusqu'à la remise en état.</p>
<h2>5. Débit d'air insuffisant</h2>
<p>Causes fréquentes : filtres colmatés, courroie qui patine, registres partiellement fermés, batterie encrassée.
Vérifier la perte de charge des filtres avant toute autre opération.</p>
""",
            """
<h2>6. Bruits anormaux</h2>
<p>Un sifflement provient généralement d'un défaut d'étanchéité des panneaux ou d'une courroie qui patine.
Un claquement métallique indique un élément desserré ou un corps étranger dans la turbine : arrêter la CTA
et inspecter après consignation.</p>
<h2>7. Remplacement des filtres</h2>
<ol>
<li>Arrêter la CTA et consigner l'alimentation électrique.</li>
<li>Déposer les filtres usagés en les ensachant pour limiter la dispersion des poussières.</li>
<li>Contrôler l'état des glissières et des joints d'étanchéité.</li>
<li>Installer des filtres neufs de même classe d'efficacité, en respectant le sens de l'air.</li>
<li>Remettre en service et relever la nouvelle perte de charge de référence.</li>
</ol>
<h2>8. Remise en service et essais</h2>
<p>Après toute intervention sur la ventilation : vérifier le sens de rotation, mesurer l'intensité absorbée,
contrôler l'absence de vibration anormale et consigner les mesures dans le rapport d'intervention.</p>
""",
        ],
    },
    {
        "file": "guide_groupes_froids_climatisation.pdf",
        "title": "Guide de dépannage - Groupes froids et climatisation gamme FrigoLine (fictif)",
        "pages": [
            """
<h1>Guide de dépannage<br/>Groupes froids et climatisation - gamme FrigoLine</h1>
<p class="note">Document fictif rédigé pour une démonstration. Fabricant et références imaginaires.</p>
<h2>1. Sécurité et réglementation des fluides frigorigènes</h2>
<p>La manipulation des fluides frigorigènes (récupération, charge, contrôle d'étanchéité) est réservée au personnel
titulaire d'une attestation de capacité, au sein d'une entreprise elle-même certifiée. Le dégazage volontaire est
interdit. Les quantités chargées et récupérées sont tracées dans le registre de l'équipement. Les contrôles
d'étanchéité périodiques dépendent de la charge de fluide de l'installation.</p>
<h2>2. La climatisation ne refroidit plus</h2>
<h3>2.1 Causes possibles</h3>
<ul>
<li>Charge insuffisante en fluide frigorigène, presque toujours due à une fuite.</li>
<li>Condenseur encrassé ou ventilateur de condenseur hors service.</li>
<li>Compresseur en défaut thermique ou contacteur défectueux.</li>
<li>Filtre de l'unité intérieure colmaté, réduisant le débit d'air.</li>
<li>Erreur de consigne ou défaut de sonde de régulation.</li>
</ul>
<h3>2.2 Démarche</h3>
<p>Contrôler d'abord les filtres et la propreté du condenseur, puis relever les pressions haute et basse, la
surchauffe et le sous-refroidissement. Ne jamais compléter la charge en fluide sans avoir recherché et réparé
la fuite : un appoint répété sans réparation masque le défaut et constitue une non-conformité.</p>
""",
            """
<h2>3. Déclenchement en sécurité haute pression (HP)</h2>
<p>Causes fréquentes : condenseur encrassé, ventilateur de condenseur à l'arrêt, température extérieure très
élevée, présence d'incondensables dans le circuit ou surcharge en fluide. Nettoyer le condenseur, vérifier le
fonctionnement des ventilateurs puis réarmer le pressostat HP. Un déclenchement HP répété après nettoyage
nécessite un diagnostic approfondi par un frigoriste.</p>
<h2>4. Déclenchement en sécurité basse pression (BP)</h2>
<p>Causes fréquentes : manque de fluide (fuite), détendeur défectueux, filtre déshydrateur colmaté, débit d'air
insuffisant sur l'évaporateur. La recherche de fuite se fait au détecteur électronique ou par traceur.</p>
<h2>5. Climatisation des salles serveurs</h2>
<p>Pour les locaux critiques, prévoir une redondance des unités et une supervision de la température avec report
d'alarme. En cas de défaillance, un climatiseur mobile d'appoint peut être installé à titre provisoire en
attendant la réparation.</p>
<h2>6. Entretien préventif</h2>
<ul>
<li>Nettoyage des filtres des unités intérieures : mensuel en période d'utilisation.</li>
<li>Nettoyage des condenseurs : au moins une fois par an, avant la saison chaude.</li>
<li>Contrôle des pressions et de l'intensité du compresseur : à chaque visite préventive.</li>
</ul>
""",
        ],
    },
    {
        "file": "guide_tableaux_electriques_bt.pdf",
        "title": "Tableaux électriques basse tension - maintenance et diagnostic des déclenchements (fictif)",
        "pages": [
            """
<h1>Tableaux électriques basse tension<br/>Maintenance et diagnostic des déclenchements</h1>
<p class="note">Guide technique fictif rédigé pour une démonstration.</p>
<h2>1. Prérequis</h2>
<p>Toute intervention sur un tableau électrique nécessite une habilitation électrique adaptée à l'opération
(par exemple BR pour le dépannage, BC pour la consignation) et le respect de la procédure de consignation.
Les mesures sous tension se font avec des équipements de protection et des appareils de mesure adaptés.</p>
<h2>2. Maintenance préventive</h2>
<ul>
<li>Thermographie infrarouge annuelle, en charge, pour détecter les échauffements de connexions.</li>
<li>Resserrage des connexions selon les couples préconisés, hors tension.</li>
<li>Test des dispositifs différentiels par le bouton test : tous les six mois.</li>
<li>Dépoussiérage du tableau et contrôle de l'état des repérages.</li>
</ul>
<h2>3. Déclenchements récurrents d'un disjoncteur</h2>
<h3>3.1 Identifier le type de déclenchement</h3>
<ul>
<li>Déclenchement thermique : surcharge prolongée du circuit.</li>
<li>Déclenchement magnétique : court-circuit.</li>
<li>Déclenchement différentiel : défaut d'isolement ou courant de fuite vers la terre.</li>
</ul>
<h3>3.2 Démarche de diagnostic</h3>
<p>Mesurer le courant de charge du circuit avec une pince ampèremétrique. Réaliser une mesure de résistance
d'isolement des circuits concernés : pour un circuit basse tension usuel, une valeur inférieure à 0,5 MΩ sous
500 V indique un défaut. Localiser ensuite le défaut par sectionnement, circuit par circuit. Les luminaires,
les prises en zone humide et les équipements extérieurs sont des causes fréquentes de défaut d'isolement.</p>
""",
            """
<h3>3.3 Bonnes pratiques</h3>
<p>Ne jamais remplacer un disjoncteur par un calibre supérieur pour supprimer des déclenchements sans étude
préalable : cela supprime la protection du câble. Un disjoncteur qui déclenche protège l'installation ; il faut
traiter la cause. Lorsqu'un déclenchement se répète malgré les corrections, documenter chaque événement (date,
heure, conditions d'utilisation) pour corréler le défaut à un usage particulier.</p>
<h2>4. Échauffements de connexions</h2>
<p>Un point chaud détecté par thermographie résulte le plus souvent d'une connexion desserrée ou oxydée. Après
resserrage, réaliser une nouvelle mesure en charge pour confirmer la correction. Un écart de température
important entre phases d'un même départ doit être analysé.</p>
<h2>5. Traçabilité</h2>
<p>Chaque intervention est consignée dans le registre de maintenance du tableau, avec les valeurs mesurées.</p>
""",
        ],
    },
    {
        "file": "guide_reseaux_hydrauliques_chauffage.pdf",
        "title": "Réseaux hydrauliques de chauffage - détection et traitement des fuites (fictif)",
        "pages": [
            """
<h1>Réseaux hydrauliques de chauffage<br/>Détection et traitement des fuites</h1>
<p class="note">Guide technique fictif rédigé pour une démonstration.</p>
<h2>1. Rappels de fonctionnement</h2>
<p>Dans un bâtiment de faible hauteur, la pression de service d'un circuit de chauffage se situe généralement
entre 1 et 2 bar à froid. Le vase d'expansion absorbe la dilatation de l'eau ; la soupape de sécurité, souvent
tarée à 3 bar, protège l'installation contre les surpressions.</p>
<h2>2. Signes d'une fuite</h2>
<ul>
<li>Baisse régulière de la pression du circuit.</li>
<li>Appoints d'eau fréquents, visibles sur le compteur d'appoint.</li>
<li>Traces d'humidité, de calcaire ou de corrosion sur les raccords, vannes et circulateurs.</li>
</ul>
<h2>3. Recherche de fuite</h2>
<p>Isoler le réseau par tronçons à l'aide des vannes et observer l'évolution de la pression de chaque tronçon.
Inspecter en priorité les raccords, les presse-étoupes de vannes, les joints de circulateurs et les purgeurs
automatiques. Dans les vides sanitaires, rechercher les traces au sol.</p>
<h2>4. Traitement</h2>
<p>Remplacer les joints ou presse-étoupes défectueux, puis remettre le circuit en eau, purger l'air et ajuster la
pression. Surveiller la pression pendant 24 heures pour confirmer l'étanchéité.</p>
""",
            """
<h2>5. Vase d'expansion</h2>
<p>Un vase d'expansion dégonflé provoque des variations de pression importantes et des déclenchements de la
soupape, qui peuvent être confondus avec une fuite. Contrôler la pression de prégonflage du vase une fois par an,
circuit vidangé côté vase.</p>
<h2>6. Qualité de l'eau</h2>
<p>Des appoints fréquents introduisent de l'oxygène et des minéraux dans le réseau, ce qui favorise la corrosion
et l'embouage. Après une fuite importante, contrôler la qualité de l'eau du circuit et, si nécessaire, prévoir
un traitement adapté.</p>
<h2>7. Fuites sur les surpresseurs et réseaux d'eau froide</h2>
<p>Sur les pompes de surpression, une fuite au niveau de l'arbre provient du presse-étoupe ou de la garniture
mécanique. Un resserrage du presse-étoupe peut suffire ; une garniture mécanique fuyarde doit être remplacée.</p>
""",
        ],
    },
    {
        "file": "procedure_salles_techniques_serveurs.pdf",
        "title": "Procédure - Surveillance des salles techniques et salles serveurs (fictif)",
        "pages": [
            """
<h1>Procédure interne<br/>Surveillance des salles techniques et salles serveurs</h1>
<p class="note">Procédure fictive rédigée pour une démonstration.</p>
<h2>1. Conditions d'ambiance recommandées</h2>
<p>La plage de température recommandée en entrée d'air des équipements informatiques est de 18 à 27 °C, avec une
humidité relative maîtrisée. Au-delà, le risque de défaillance des équipements augmente.</p>
<h2>2. Seuils d'alerte de la procédure</h2>
<table>
<tr><th>Niveau</th><th>Seuil</th><th>Action attendue</th></tr>
<tr><td>Alerte</td><td>27 °C</td><td>Vérification sous 4 heures par le technicien d'astreinte</td></tr>
<tr><td>Alarme critique</td><td>30 °C</td><td>Intervention immédiate et information du responsable informatique</td></tr>
</table>
<h2>3. Conduite à tenir en cas de défaut de température</h2>
<ol>
<li>Vérifier le fonctionnement des unités de climatisation et l'absence d'alarme sur les groupes.</li>
<li>Contrôler que les portes de la salle sont fermées et que les flux d'air ne sont pas obstrués.</li>
<li>Nettoyer les filtres des unités intérieures si nécessaire.</li>
<li>Si la température dépasse le seuil d'alarme, installer un climatiseur mobile d'appoint et prévenir le
responsable informatique, qui décide d'un éventuel délestage des équipements.</li>
<li>Faire intervenir un frigoriste certifié si un défaut frigorifique est suspecté.</li>
</ol>
""",
            """
<h2>4. Supervision</h2>
<p>Chaque salle serveurs doit être équipée d'au moins deux sondes de température avec report d'alarme vers le
poste de supervision et le technicien d'astreinte. Les courbes de température sont conservées au moins 12 mois
afin d'analyser les incidents répétés.</p>
<h2>5. Maintenance des installations de climatisation des salles serveurs</h2>
<ul>
<li>Redondance recommandée de type N+1 pour les unités de climatisation.</li>
<li>Test de bascule entre unités : semestriel.</li>
<li>Nettoyage des filtres : mensuel.</li>
</ul>
<h2>6. Retour d'expérience</h2>
<p>Deux défauts de température en moins de 30 jours sur une même salle doivent donner lieu à une analyse des
causes et à un plan d'action partagé avec le gestionnaire du bâtiment.</p>
""",
        ],
    },
]
