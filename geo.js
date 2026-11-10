const nearbyCities = require('nearby-cities');

function getDistance(lat1, lon1, lat2, lon2) {
    const R = 6371;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
              Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
              Math.sin(dLon / 2) * Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
}

function getBestLocation(lat, lon, config) {
    const rawCities = nearbyCities({ latitude: lat, longitude: lon });
    if (rawCities.length === 0) return null;

    const candidates = rawCities.slice(0, 50).map(city => {
        const dist = getDistance(lat, lon, city.lat, city.lon);
        return { ...city, dist, score: city.population / ((dist * 3) + 1) };
    });

    candidates.sort((a, b) => b.score - a.score);

    const best = candidates[0];
    let cityName = best.name;
    let countryCode = best.country;

    if (config.CITY_OVERRIDES[cityName]) {
        cityName = config.CITY_OVERRIDES[cityName];
    }

    let locationStr = "";
    if (countryCode === "FR") {
        locationStr = cityName;
    } else {
        const fullCountry = config.COUNTRY_NAMES[countryCode] || countryCode;
        locationStr = `${cityName} (${fullCountry})`;
    }

    let duel = "";
    if (candidates.length > 1) {
        duel = ` [Match: ${best.name}(${Math.round(best.score)}) > ${candidates[1].name}(${Math.round(candidates[1].score)})]`;
    }

    return {
        label: locationStr,
        status: `Trouvé : ${cityName} (${best.dist.toFixed(1)}km)${duel}`
    };
}

module.exports = {
    getBestLocation,
    getDistance
};
