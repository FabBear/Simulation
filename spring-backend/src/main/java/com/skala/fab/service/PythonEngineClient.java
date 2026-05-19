package com.skala.fab.service;

import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;
import java.util.Map;

@Component
@ConditionalOnProperty(name = "engine.mode", havingValue = "python", matchIfMissing = true)
public class PythonEngineClient {
    private final RestTemplate restTemplate;
    private final String engineBaseUrl;

    public PythonEngineClient(
        RestTemplateBuilder builder,
        @Value("${engine.base-url:http://127.0.0.1:8000}") String engineBaseUrl
    ) {
        this.restTemplate = builder
            .setConnectTimeout(Duration.ofSeconds(5))
            .setReadTimeout(Duration.ofSeconds(30))
            .build();
        this.engineBaseUrl = engineBaseUrl;
    }

    public JsonNode get(String path) {
        ResponseEntity<JsonNode> response = restTemplate.getForEntity(engineBaseUrl + path, JsonNode.class);
        return response.getBody();
    }

    public JsonNode post(String path) {
        ResponseEntity<JsonNode> response = restTemplate.postForEntity(engineBaseUrl + path, null, JsonNode.class);
        return response.getBody();
    }

    public JsonNode post(String path, Map<String, Object> body) {
        ResponseEntity<JsonNode> response = restTemplate.postForEntity(engineBaseUrl + path, body, JsonNode.class);
        return response.getBody();
    }

    public JsonNode request(HttpMethod method, String path, Map<String, Object> body) {
        HttpEntity<Map<String, Object>> req = new HttpEntity<>(body);
        ResponseEntity<JsonNode> response = restTemplate.exchange(engineBaseUrl + path, method, req, JsonNode.class);
        return response.getBody();
    }
}
