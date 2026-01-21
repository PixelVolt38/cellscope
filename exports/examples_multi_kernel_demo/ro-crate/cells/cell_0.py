# climate data frame
import pandas as pd
from statistics import mean

readings = [22.1, 21.8, 23.4, 24.0, 22.7]
locations = ["north", "south", "east", "west", "central"]
climate = pd.DataFrame({"location": locations, "temperature": readings})
climate['temperature_c'] = climate['temperature']
climate_summary = {
    'mean_c': mean(readings),
    'max_c': max(readings),
    'min_c': min(readings)
}
