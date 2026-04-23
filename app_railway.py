"""
Bot Tarot - Application Web pour Railway
Interface moderne et simple pour l'interprétation de cartes tarot
"""

from flask import Flask, render_template, request, jsonify, session
import json
import random
import os
from datetime import datetime
from anthropic import Anthropic
import secrets

# Configuration Flask pour Railway
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(16))
app.config['SESSION_TYPE'] = 'filesystem'

# Initialiser le client Anthropic
anthropic_client = Anthropic()

# Charger les données
def load_data():
    """Charge les arcanes et les tirages depuis les fichiers JSON"""
    script_dir = os.path.dirname(os.path.abspath(__file__))

    with open(os.path.join(script_dir, 'arcanes.json'), 'r', encoding='utf-8') as f:
        arcanes_data = json.load(f)

    with open(os.path.join(script_dir, 'spreads.json'), 'r', encoding='utf-8') as f:
        spreads_data = json.load(f)

    return arcanes_data['arcanes'], spreads_data['spreads']

ARCANES, SPREADS = load_data()
ARCANES_BY_ID = {arcane['id']: arcane for arcane in ARCANES}

class TarotSession:
    """Gère une session tarot pour un utilisateur"""

    def __init__(self):
        self.conversation_history = []
        self.current_spread = None
        self.current_cards = None
        self.question = None

    def get_system_prompt(self):
        return """Tu es un expert en tarot bienveillant et pédagogue, spécialisé dans l'aide aux débutants.

DIRECTIVES IMPORTANTES:
1. **Clarté**: Explique simplement et clairement
2. **Pédagogie**: Enseigne comment lire les cartes, pas juste la réponse
3. **Bienveillance**: Sois encourageant et positif
4. **Concision**: Réponds en 2-3 paragraphes max
5. **Pratique**: Donne des conseils applicables

Réponds en français, directement et sans détours."""

    def draw_cards(self, nbcartes):
        """Tire aléatoirement des cartes"""
        drawn = random.sample(range(22), nbcartes)
        return [ARCANES_BY_ID[card_id] for card_id in drawn]

    def get_claude_response(self, user_message):
        """Appelle Claude API"""
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        try:
            response = anthropic_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=800,
                system=self.get_system_prompt(),
                messages=self.conversation_history
            )

            assistant_message = response.content[0].text

            self.conversation_history.append({
                "role": "assistant",
                "content": assistant_message
            })

            return assistant_message
        except Exception as e:
            return f"Erreur lors de la connexion à Claude: {str(e)}. Vérifiez votre clé API."

    def perform_spread(self, spread_id, question=""):
        """Effectue un tirage"""
        spread = next((s for s in SPREADS if s['id'] == spread_id), None)
        if not spread:
            return None

        self.current_spread = spread
        self.current_cards = self.draw_cards(spread['nbcartes'])
        self.question = question

        # Préparer le contexte pour Claude
        cards_info = []
        for i, position_info in enumerate(spread['positions']):
            card = self.current_cards[i]
            orientation = random.choice(['endroit', 'envers'])

            card_data = {
                'position': i + 1,
                'nom': card['nom'],
                'numero': card['numero'],
                'position_nom': position_info['nom'],
                'orientation': orientation,
                'interpretation': card[orientation]['interpretation'],
                'mots_cles': card[orientation]['mots_cles']
            }
            cards_info.append(card_data)

        # Créer le prompt pour Claude
        prompt = f"""
TIRAGE: {spread['nom']}
Question: {question if question else 'Pas de question spécifique'}

CARTES TIRÉES:
"""
        for info in cards_info:
            prompt += f"\n{info['position']}. {info['nom']} ({info['orientation'].upper()})"
            prompt += f"\n   Position: {info['position_nom']}"
            prompt += f"\n   Interprétation: {info['interpretation']}"

        prompt += f"""

Fournis une interprétation BRÈVE (3-4 phrases) et pédagogique:
1. Résumé rapide (1-2 phrases)
2. Un conseil pratique
3. Une question pour approfondir

Sois clair et accessible pour un débutant."""

        interpretation = self.get_claude_response(prompt)

        return {
            'spread': spread,
            'cards': cards_info,
            'interpretation': interpretation
        }

    def ask_followup(self, question):
        """Pose une question de suivi"""
        if not self.current_spread:
            return "Veuillez d'abord effectuer un tirage."

        msg = f"Le consultant demande: {question}\n\nRéponds en gardant le contexte du tirage actuel."
        return self.get_claude_response(msg)

# Routes

@app.route('/')
def index():
    """Page principale"""
    return render_template('index_railway.html')

@app.route('/api/spreads')
def api_spreads():
    """API - Retourne les tirages disponibles"""
    return jsonify([{
        'id': s['id'],
        'nom': s['nom'],
        'nom_court': s['nom_court'],
        'description': s['description'],
        'nbcartes': s['nbcartes'],
        'difficulte': s['difficulte']
    } for s in SPREADS])

@app.route('/api/perform-spread', methods=['POST'])
def api_perform_spread():
    """API - Effectue un tirage"""
    data = request.json
    spread_id = data.get('spread_id')
    question = data.get('question', '')

    # Créer une session pour cet utilisateur
    if 'tarot_session' not in session or not session['tarot_session']:
        session['tarot_session'] = None

    tarot = TarotSession()
    result = tarot.perform_spread(spread_id, question)

    if result:
        # Sauvegarder la session
        session['tarot_data'] = {
            'spread_id': spread_id,
            'question': question,
            'conversation': tarot.conversation_history,
            'cards': [
                {
                    'nom': c['nom'],
                    'numero': c['numero'],
                    'orientation': c['orientation'],
                    'position_nom': c['position_nom'],
                    'mots_cles': c['mots_cles'],
                    'interpretation': c['interpretation']
                } for c in result['cards']
            ]
        }
        session.modified = True

        return jsonify({
            'success': True,
            'spread_name': result['spread']['nom'],
            'cards': result['cards'],
            'interpretation': result['interpretation']
        })
    else:
        return jsonify({'success': False, 'error': 'Tirage non trouvé'}), 404

@app.route('/api/ask-followup', methods=['POST'])
def api_ask_followup():
    """API - Question de suivi"""
    data = request.json
    question = data.get('question', '')

    if not question:
        return jsonify({'success': False, 'error': 'Question vide'}), 400

    if 'tarot_data' not in session:
        return jsonify({'success': False, 'error': 'Aucun tirage en cours'}), 400

    # Recréer la session avec l'historique
    tarot = TarotSession()
    tarot.conversation_history = session.get('tarot_data', {}).get('conversation', [])

    response = tarot.ask_followup(question)

    # Mettre à jour l'historique
    if 'tarot_data' in session:
        session['tarot_data']['conversation'] = tarot.conversation_history
        session.modified = True

    return jsonify({
        'success': True,
        'response': response
    })

@app.route('/api/guide')
def api_guide():
    """API - Retourne les infos pour le guide"""
    return jsonify({
        'arcanes': [
            {
                'id': a['id'],
                'nom': a['nom'],
                'numero': a['numero'],
                'signification': a['signification_generale'],
                'conseil': a['conseil_debutant']
            } for a in ARCANES
        ],
        'spreads': [{
            'nom': s['nom'],
            'description': s['description'],
            'nbcartes': s['nbcartes']
        } for s in SPREADS]
    })

@app.route('/health')
def health():
    """Health check pour Railway"""
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
