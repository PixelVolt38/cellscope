# reference external configuration for provenance
config_path = 'config/thresholds.txt'
with open(config_path) as handle:
    thresholds = [float(line.strip()) for line in handle if line.strip()]

baseline = thresholds[0] if thresholds else None
print('baseline threshold:', baseline)
