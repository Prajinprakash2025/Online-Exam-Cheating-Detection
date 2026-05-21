RISK_RULES = {
    'phone_detected': {
        'label': 'Mobile Phone Detected',
        'points': 45,
        'cap': 70,
        'severity': 'critical',
    },
    'multi_face': {
        'label': 'Multiple Persons',
        'points': 40,
        'cap': 80,
        'severity': 'critical',
    },
    'tab_switch': {
        'label': 'Tab / Window Switch',
        'points': 30,
        'cap': 90,
        'severity': 'high',
    },
    'no_face': {
        'label': 'Face Absence',
        'points': 18,
        'cap': 60,
        'severity': 'high',
    },
    'head_pose': {
        'label': 'Suspicious Head Movement',
        'points': 12,
        'cap': 48,
        'severity': 'medium',
    },
    'gaze_deviation': {
        'label': 'Eye Gaze Deviation',
        'points': 10,
        'cap': 40,
        'severity': 'medium',
    },
}


def calculate_risk_report(logs):
    counts = {}
    total = 0
    breakdown = []

    for log in logs:
        counts[log.violation_type] = counts.get(log.violation_type, 0) + 1

    for violation_type, count in counts.items():
        rule = RISK_RULES.get(violation_type, {
            'label': violation_type.replace('_', ' ').title(),
            'points': 8,
            'cap': 30,
            'severity': 'low',
        })
        raw_points = rule['points'] * count
        points = min(raw_points, rule['cap'])
        total += points
        breakdown.append({
            'type': violation_type,
            'label': rule['label'],
            'count': count,
            'points': points,
            'severity': rule['severity'],
        })

    score = min(total, 100)

    if score >= 80:
        level = 'Critical'
        color = 'danger'
        recommendation = 'Strong integrity breach pattern. Review evidence carefully before publishing marks.'
    elif score >= 55:
        level = 'High'
        color = 'danger'
        recommendation = 'High-risk session. Evidence review is recommended before approval.'
    elif score >= 25:
        level = 'Medium'
        color = 'warning'
        recommendation = 'Some suspicious activity detected. Check timeline and snapshots.'
    else:
        level = 'Low'
        color = 'success'
        recommendation = 'No significant suspicious pattern detected.'

    breakdown.sort(key=lambda item: item['points'], reverse=True)

    return {
        'score': score,
        'level': level,
        'color': color,
        'recommendation': recommendation,
        'total_events': sum(counts.values()),
        'breakdown': breakdown,
    }
