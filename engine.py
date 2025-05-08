from flask import Flask, render_template, request, jsonify
import psycopg2
from datetime import datetime
import matplotlib.pyplot as plt
from io import BytesIO
import base64
import numpy as np

app = Flask(__name__)

# Database configuration
DB_CONFIG = {
    'dbname': 'baby_feeding_db',
    'user': 'postgres',
    'password': '1234',
    'host': 'localhost'
}

def get_db_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print("Database connection error:", str(e))
        raise

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/submit_feeding', methods=['POST'])
def submit_feeding():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No data received'}), 400

        feeding_date = data.get('feeding_date')
        feeding_time = data.get('feeding_time')
        feeding_item = data.get('feeding_item')
        volume_prepared = data.get('volume_prepared')
        volume_left = data.get('volume_left')

        if not all([feeding_date, feeding_time, feeding_item, volume_prepared, volume_left]):
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400

        try:
            volume_prepared = round(float(volume_prepared))
        except ValueError:
            return jsonify({'status': 'error', 'message': 'Prepared volume must be a number'}), 400

        try:
            volume_left = int(volume_left.rstrip('%'))
        except ValueError:
            return jsonify({'status': 'error', 'message': 'Invalid leftover percentage'}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute(
            "INSERT INTO feed_records (feeding_date, feeding_time, feeding_item, volume_prepared, volume_left) VALUES (%s, %s, %s, %s, %s)",
            (feeding_date, feeding_time, feeding_item, volume_prepared, volume_left)
        )
        
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Feeding record added successfully!'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

@app.route('/submit_allergy', methods=['POST'])
def submit_allergy():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No data received'}), 400

        record_date = data.get('allergy_date')
        has_allergy = data.get('has_allergy') == True
        suspected_item = data.get('suspected_item', '')
        symptoms = data.get('symptoms', '')

        if not record_date:
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute(
            "INSERT INTO allergy_records (record_date, has_allergy, suspected_item, symptoms) VALUES (%s, %s, %s, %s)",
            (record_date, has_allergy, suspected_item, symptoms)
        )
        
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Allergy record added successfully!'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

@app.route('/get_feeding_items')
def get_feeding_items():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT DISTINCT feeding_item as item
            FROM feed_records 
            WHERE feeding_item IS NOT NULL AND feeding_item != ''
            ORDER BY item
        """)
        items = [item[0] for item in cur.fetchall()]
        
        return jsonify({
            'status': 'success',
            'items': items if items else []
        })
    except Exception as e:
        print("Database error:", str(e))
        return jsonify({
            'status': 'error',
            'message': 'Database error: ' + str(e)
        }), 500
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

@app.route('/get_analytics')
def get_analytics():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                feeding_item,
                COUNT(*) as frequency,
                ROUND(AVG(volume_prepared - (volume_prepared * volume_left / 100.0)), 1) as avg_consumed,
                ROUND(AVG(volume_prepared), 1) as avg_prepared
            FROM feed_records
            GROUP BY feeding_item
            ORDER BY COUNT(*) DESC, AVG(volume_prepared - (volume_prepared * volume_left / 100.0)) DESC
        """)
        consumption_data = cur.fetchall()
        
        cur.execute("""
            SELECT 
                suspected_item,
                COUNT(*) as allergy_count,
                STRING_AGG(symptoms, '; ') as all_symptoms
            FROM allergy_records
            WHERE has_allergy = TRUE 
            AND suspected_item IS NOT NULL 
            AND suspected_item != ''
            GROUP BY suspected_item
            ORDER BY COUNT(*) DESC
        """)
        allergen_data = cur.fetchall()
        
        confirmed_allergens = {row[0]: {'count': row[1], 'symptoms': row[2]} for row in allergen_data}
        
        items = [row[0] for row in consumption_data]
        frequencies = [row[1] for row in consumption_data]
        avg_consumed = [row[2] for row in consumption_data]
        avg_prepared = [row[3] for row in consumption_data]
        
        plt.figure(figsize=(10, 6))
        x = np.arange(len(items))
        width = 0.35
        
        bars1 = plt.bar(x - width/2, frequencies, width, label='Frequency')
        bars2 = plt.bar(x + width/2, avg_consumed, width, label='Avg Consumed (tbsp)')
        
        for bar in bars1:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height,
                    f'{int(height)}',
                    ha='center', va='bottom')
        
        for bar in bars2:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.1f}',
                    ha='center', va='bottom')
        
        plt.xlabel('Food Items')
        plt.ylabel('Count')
        plt.title('Baby Food Preferences')
        plt.xticks(x, items, rotation=45, ha='right')
        plt.legend()
        plt.tight_layout()
        
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        buf.seek(0)
        plot_url = base64.b64encode(buf.getvalue()).decode('utf-8')
        plt.close()
        
        suggestions = []
        for i in range(min(3, len(consumption_data))):
            item = consumption_data[i]
            is_allergen = item[0] in confirmed_allergens
            allergy_info = confirmed_allergens.get(item[0], {})
            
            suggestions.append({
                'item': item[0],
                'avg_consumed': item[2],
                'consumption_rate': round((item[2] / item[3]) * 100) if item[3] else 0,
                'is_allergen': is_allergen,
                'allergy_count': allergy_info.get('count', 0),
                'symptoms': allergy_info.get('symptoms', '')
            })
        
        return jsonify({
            'status': 'success',
            'plot_url': plot_url,
            'items': items,
            'frequencies': frequencies,
            'avg_consumed': avg_consumed,
            'suggestions': suggestions,
            'confirmed_allergens': [{'item': k, 'count': v['count'], 'symptoms': v['symptoms']} 
                                  for k, v in confirmed_allergens.items()]
        })
        
    except Exception as e:
        print("Error in analytics:", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=True)