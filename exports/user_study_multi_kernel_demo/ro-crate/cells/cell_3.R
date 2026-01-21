# consume SoS hand-off and CSV artifact
summary <- climate_summary
summary[['mean_c', 'max_c', 'min_c']]

# Pretend to load the CSV produced by Python (path kept for provenance capture)
climate_frame <- read.csv('data_outputs/climate_readings.csv')
head(climate_frame)