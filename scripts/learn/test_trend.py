from app.analysis.trend import analyze_health_trend


scores = [
    82,
    75,
    68,
    55,
    45
]


result = analyze_health_trend(scores)


print(result)
